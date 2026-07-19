from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes

from courses.models import ClassroomGroup, ClassroomGroupCollaboration, ClassroomGroupMember, ClassroomSession
from learning.models import LearningEvent
from learning_analytics.services.dual_write import (
    EventWriteError,
    record_classroom_point_adjustment,
    record_learning_event,
)
from learning_analytics.services.operational_events import (
    record_chat_message_sent,
    record_intervention_acknowledged,
)
from realtime.events import publish_chat_event, session_group, teacher_group, user_group
from realtime.models import ClassroomChatConfig, ClassroomChatMessage, ClassroomChatReadState, ClassroomChatThread
from realtime.moderation import DEFAULT_DEDUCTION, SEVERITY_RANK, moderate_content
from realtime.serializers import chat_message_row, chat_thread_target_row, chat_user_row
from school.models import StudentProfile

from .permissions import IsStudent, IsTeacher
from .responses import fail, ok


ROOM_CONFIG_FIELDS = {
    ClassroomChatThread.RoomType.WHOLE_CLASS: "whole_class_enabled",
    ClassroomChatThread.RoomType.TEACHER_PRIVATE: "teacher_private_enabled",
    ClassroomChatThread.RoomType.GROUP: "group_chat_enabled",
}


class ChatError(Exception):
    def __init__(self, message: str, *, status: int = 400, errors: dict | None = None):
        self.message = message
        self.status = status
        self.errors = errors or {}
        super().__init__(message)


def _chat_fail(exc: ChatError):
    return fail(exc.message, errors=exc.errors, status=exc.status)


def _teacher_session(request, session_id) -> ClassroomSession:
    try:
        session_id = int(session_id)
    except (TypeError, ValueError):
        raise ChatError("课堂编号不正确。", status=404)
    session = (
        ClassroomSession.objects.select_related("teacher", "course", "lesson", "class_group")
        .filter(pk=session_id, school=request.user.school, teacher=request.user)
        .first()
    )
    if session is None:
        raise ChatError("课堂不存在或无权操作。", status=404)
    return session


def _student_session(request, session_id) -> tuple[ClassroomSession, StudentProfile]:
    profile = (
        StudentProfile.objects.select_related("user", "class_group")
        .filter(user=request.user, user__school=request.user.school)
        .first()
    )
    if profile is None or not profile.class_group_id:
        raise ChatError("学生档案或班级信息不完整。", status=403)
    try:
        session_id = int(session_id)
    except (TypeError, ValueError):
        raise ChatError("课堂编号不正确。", status=404)
    session = (
        ClassroomSession.objects.select_related("teacher", "course", "lesson", "class_group")
        .filter(pk=session_id, school=request.user.school, class_group=profile.class_group)
        .first()
    )
    if session is None:
        raise ChatError("课堂不存在或无权进入。", status=404)
    if session.status != ClassroomSession.Status.RUNNING:
        raise ChatError("课堂已结束，聊天已关闭。", status=403)
    return session, profile


def _chat_config(session: ClassroomSession) -> ClassroomChatConfig:
    config, _ = ClassroomChatConfig.objects.get_or_create(session=session)
    return config


def _active_collaboration(session: ClassroomSession) -> ClassroomGroupCollaboration | None:
    return (
        ClassroomGroupCollaboration.objects.filter(
            session=session,
            is_enabled=True,
            status=ClassroomGroupCollaboration.Status.OPEN,
        )
        .first()
    )


def _class_students(session: ClassroomSession) -> list[StudentProfile]:
    return list(
        StudentProfile.objects.filter(
            class_group=session.class_group,
            user__school=session.school,
            user__role="student",
            user__is_active=True,
        )
        .select_related("user")
        .order_by("user__display_name", "user__username")
    )


def _collaboration_groups(collaboration: ClassroomGroupCollaboration | None) -> list[ClassroomGroup]:
    if collaboration is None:
        return []
    return list(
        ClassroomGroup.objects.filter(collaboration=collaboration)
        .prefetch_related("members__student")
        .order_by("group_no", "id")
    )


def _room_enabled(config: ClassroomChatConfig, room_type: str) -> bool:
    field = ROOM_CONFIG_FIELDS.get(room_type)
    return bool(field and getattr(config, field))


def _parse_room_type(value: object) -> str:
    room_type = str(value or "").strip()
    if room_type not in {item.value for item in ClassroomChatThread.RoomType}:
        raise ChatError("聊天类型不正确。", errors={"room_type": ["请选择全班、教师私聊或小组聊天。"]})
    return room_type


def _parse_target_id(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        target_id = int(value)
    except (TypeError, ValueError):
        raise ChatError("聊天对象不正确。", errors={"target_id": ["聊天对象编号不正确。"]})
    if target_id < 1:
        raise ChatError("聊天对象不正确。", errors={"target_id": ["聊天对象编号不正确。"]})
    return target_id


def _resolve_thread(
    session: ClassroomSession,
    user,
    room_type: str,
    target_id: int | None,
    *,
    create: bool,
) -> ClassroomChatThread | None:
    query = ClassroomChatThread.objects.select_related("session", "student", "group")
    filters: dict = {"session": session, "room_type": room_type}

    if room_type == ClassroomChatThread.RoomType.WHOLE_CLASS:
        if target_id is not None:
            raise ChatError("全班聊天不需要指定聊天对象。")
    elif room_type == ClassroomChatThread.RoomType.TEACHER_PRIVATE:
        student_id = user.id if user.role == "student" else target_id
        if not student_id:
            raise ChatError("请选择需要私聊的学生。", errors={"target_id": ["请选择学生。"]})
        student_profile = (
            StudentProfile.objects.select_related("user")
            .filter(
                user_id=student_id,
                user__school=session.school,
                user__role="student",
                user__is_active=True,
                class_group=session.class_group,
            )
            .first()
        )
        if student_profile is None:
            raise ChatError("学生不在当前课堂班级中。", status=403)
        filters["student"] = student_profile.user
    else:
        if not target_id:
            raise ChatError("请选择小组。", errors={"target_id": ["请选择小组。"]})
        collaboration = _active_collaboration(session)
        group = ClassroomGroup.objects.filter(pk=target_id, collaboration=collaboration).first()
        if group is None:
            raise ChatError("小组不存在或小组合作未开启。", status=404)
        if user.role == "student" and not ClassroomGroupMember.objects.filter(group=group, student=user).exists():
            raise ChatError("只能进入自己所在的小组聊天。", status=403)
        filters["group"] = group

    thread = query.filter(**filters).first()
    if thread is None and create:
        thread, _ = ClassroomChatThread.objects.get_or_create(**filters)
        thread = query.get(pk=thread.pk)
    return thread


def _message_query_for_viewer(thread: ClassroomChatThread, viewer):
    query = thread.messages.select_related("thread", "thread__student", "thread__group", "sender", "reviewed_by")
    if viewer.role == "teacher":
        return query
    return query.filter(
        Q(moderation_status=ClassroomChatMessage.ModerationStatus.VISIBLE)
        | Q(sender=viewer, moderation_status=ClassroomChatMessage.ModerationStatus.PENDING)
    )


def _thread_unread_count(thread: ClassroomChatThread, viewer) -> int:
    state = ClassroomChatReadState.objects.filter(thread=thread, user=viewer).first()
    query = _message_query_for_viewer(thread, viewer).exclude(sender=viewer)
    if state and state.last_read_message_id:
        query = query.filter(id__gt=state.last_read_message_id)
    return query.count()


def _last_message_row(thread: ClassroomChatThread, viewer) -> dict | None:
    message = _message_query_for_viewer(thread, viewer).order_by("-id").first()
    if message is None:
        return None
    return chat_message_row(message, viewer=viewer, include_moderation=viewer.role == "teacher")


def _thread_summary(thread: ClassroomChatThread, viewer) -> dict:
    return {
        "id": thread.id,
        "room_type": thread.room_type,
        "room_type_label": thread.get_room_type_display(),
        "target": chat_thread_target_row(thread),
        "unread_count": _thread_unread_count(thread, viewer),
        "last_message": _last_message_row(thread, viewer),
        "updated_at": thread.updated_at,
    }


def _group_row(group: ClassroomGroup) -> dict:
    members = [chat_user_row(member.student) for member in group.members.all()]
    return {
        "id": group.id,
        "name": f"第{group.group_no}组",
        "group_no": group.group_no,
        "members": members,
    }


def _student_moderation_feedbacks(session: ClassroomSession, student) -> list[dict]:
    acknowledged_ids = set(
        LearningEvent.objects.filter(
            actor=student,
            object_type="classroom_chat_message",
            metadata__action="classroom_chat_moderation_feedback_ack",
        ).values_list("object_id", flat=True)
    )
    messages = (
        ClassroomChatMessage.objects.filter(
            thread__session=session,
            sender=student,
            moderation_status=ClassroomChatMessage.ModerationStatus.REMOVED,
            review_action__in=[
                ClassroomChatMessage.ReviewAction.WARN,
                ClassroomChatMessage.ReviewAction.REMOVE,
                ClassroomChatMessage.ReviewAction.DEDUCT,
            ],
        )
        .exclude(id__in=[int(value) for value in acknowledged_ids if str(value).isdigit()])
        .order_by("-reviewed_at", "-id")[:10]
    )
    return [
        {
            "id": message.id,
            "action": message.review_action,
            "action_label": message.get_review_action_display(),
            "severity": message.severity,
            "severity_label": message.get_severity_display(),
            "deduction_points": message.deduction_points,
            "note": message.review_note,
            "reviewed_at": message.reviewed_at,
        }
        for message in messages
    ]


def _context_payload(session: ClassroomSession, viewer) -> dict:
    config = _chat_config(session)
    collaboration = _active_collaboration(session)
    groups = _collaboration_groups(collaboration)
    thread_query = ClassroomChatThread.objects.filter(session=session)
    if viewer.role == "student":
        group_ids = ClassroomGroupMember.objects.filter(
            group__collaboration=collaboration,
            student=viewer,
        ).values_list("group_id", flat=True)
        thread_query = thread_query.filter(
            Q(room_type=ClassroomChatThread.RoomType.WHOLE_CLASS)
            | Q(room_type=ClassroomChatThread.RoomType.TEACHER_PRIVATE, student=viewer)
            | Q(room_type=ClassroomChatThread.RoomType.GROUP, group_id__in=group_ids)
        )
    threads = list(thread_query.select_related("student", "group").order_by("-updated_at", "-id"))
    effective_running = session.status == ClassroomSession.Status.RUNNING
    payload = {
        "session": {
            "id": session.id,
            "title": session.title,
            "status": session.status,
            "status_label": session.get_status_display(),
        },
        "me": chat_user_row(viewer),
        "teacher": chat_user_row(session.teacher),
        "settings": {
            "whole_class_enabled": config.whole_class_enabled,
            "teacher_private_enabled": config.teacher_private_enabled,
            "group_chat_enabled": config.group_chat_enabled,
        },
        "enabled": {
            "whole_class": effective_running and config.whole_class_enabled,
            "teacher_private": effective_running and config.teacher_private_enabled,
            "group": effective_running and config.group_chat_enabled and collaboration is not None,
        },
        "group_chat_available": collaboration is not None and bool(groups),
        "threads": [_thread_summary(thread, viewer) for thread in threads],
        "pending_moderation_count": (
            ClassroomChatMessage.objects.filter(
                thread__session=session,
                moderation_status=ClassroomChatMessage.ModerationStatus.PENDING,
            ).count()
            if viewer.role == "teacher"
            else 0
        ),
    }
    if viewer.role == "teacher":
        payload["students"] = [
            {
                **chat_user_row(profile.user),
                "student_no": profile.student_no,
            }
            for profile in _class_students(session)
        ]
        payload["groups"] = [_group_row(group) for group in groups]
    else:
        member = (
            ClassroomGroupMember.objects.select_related("group")
            .filter(collaboration=collaboration, student=viewer)
            .first()
            if collaboration is not None
            else None
        )
        payload["my_group"] = _group_row(next((group for group in groups if group.id == member.group_id), member.group)) if member else None
        payload["moderation_feedbacks"] = _student_moderation_feedbacks(session, viewer)
    return payload


def _message_event_groups(message: ClassroomChatMessage, *, pending_only: bool = False) -> list[str]:
    session_id = message.thread.session_id
    if pending_only:
        return [teacher_group(session_id), user_group(session_id, message.sender_id)]
    if message.thread.room_type == ClassroomChatThread.RoomType.WHOLE_CLASS:
        return [session_group(session_id)]
    if message.thread.room_type == ClassroomChatThread.RoomType.TEACHER_PRIVATE:
        return [teacher_group(session_id), user_group(session_id, message.thread.student_id)]
    student_ids = list(
        ClassroomGroupMember.objects.filter(group_id=message.thread.group_id).values_list("student_id", flat=True)
    )
    return [teacher_group(session_id), *[user_group(session_id, student_id) for student_id in student_ids]]


def _push_changed(message: ClassroomChatMessage, *, event_type: str, pending_only: bool = False) -> None:
    publish_chat_event(
        _message_event_groups(message, pending_only=pending_only),
        {
            "type": event_type,
            "session_id": message.thread.session_id,
            "message_id": message.id,
            "thread_id": message.thread_id,
            "room_type": message.thread.room_type,
            "target_id": message.thread.student_id or message.thread.group_id,
            "moderation_status": message.moderation_status,
        },
    )


def _validate_send_rate(session: ClassroomSession, sender, fingerprint: str) -> tuple[str, list[str], list[str]]:
    now = timezone.now()
    recent_query = ClassroomChatMessage.objects.filter(
        thread__session=session,
        sender=sender,
        created_at__gte=now - timedelta(seconds=10),
    )
    recent_count = recent_query.count()
    if recent_count >= 8:
        raise ChatError("发送过于频繁，请稍后再试。", status=429)

    severity = "none"
    categories: list[str] = []
    rules: list[str] = []
    repeated_count = ClassroomChatMessage.objects.filter(
        thread__session=session,
        sender=sender,
        content_fingerprint=fingerprint,
        created_at__gte=now - timedelta(seconds=60),
    ).count()
    if repeated_count >= 2:
        severity = "mild"
        categories.append("重复刷屏")
        rules.append("重复刷屏：60 秒内重复发送相同内容")
    if recent_count >= 5:
        severity = "moderate"
        categories.append("发送频率异常")
        rules.append("发送频率异常：10 秒内连续发送多条消息")
    return severity, categories, rules


@transaction.atomic
def _create_message(session: ClassroomSession, sender, room_type: str, target_id: int | None, content: object):
    config = _chat_config(session)
    if session.status != ClassroomSession.Status.RUNNING:
        raise ChatError("课堂已结束，不能继续发送消息。", status=403)
    if not _room_enabled(config, room_type):
        raise ChatError("教师尚未开启该聊天方式。", status=403)
    if room_type == ClassroomChatThread.RoomType.GROUP and _active_collaboration(session) is None:
        raise ChatError("小组合作尚未开启，不能使用小组聊天。", status=403)

    result = moderate_content(content)
    if not result.content:
        raise ChatError("请输入聊天内容。", errors={"content": ["聊天内容不能为空。"]})
    if len(result.content) > 500:
        raise ChatError("聊天内容不能超过 500 个字符。", errors={"content": ["最多输入 500 个字符。"]})

    severity = result.severity
    categories = list(result.categories)
    matched_rules = list(result.matched_rules)
    if sender.role == "student":
        rate_severity, rate_categories, rate_rules = _validate_send_rate(session, sender, result.fingerprint)
        if SEVERITY_RANK[rate_severity] > SEVERITY_RANK[severity]:
            severity = rate_severity
        categories.extend(item for item in rate_categories if item not in categories)
        matched_rules.extend(item for item in rate_rules if item not in matched_rules)

    flagged = sender.role == "student" and bool(matched_rules)
    thread = _resolve_thread(session, sender, room_type, target_id, create=True)
    message = ClassroomChatMessage.objects.create(
        thread=thread,
        sender=sender,
        content=result.content,
        content_fingerprint=result.fingerprint,
        moderation_status=(
            ClassroomChatMessage.ModerationStatus.PENDING
            if flagged
            else ClassroomChatMessage.ModerationStatus.VISIBLE
        ),
        severity=severity if flagged else ClassroomChatMessage.Severity.NONE,
        moderation_categories=categories if flagged else [],
        matched_rules=matched_rules if flagged else [],
    )
    thread.save(update_fields=["updated_at"])
    try:
        record_chat_message_sent(message=message, session=session)
    except EventWriteError as exc:
        raise ChatError(exc.message, status=500) from exc
    _push_changed(
        message,
        event_type="chat.moderation.pending" if flagged else "chat.message.created",
        pending_only=flagged,
    )
    return message


def _messages_payload(session: ClassroomSession, viewer, query_params) -> dict:
    room_type = _parse_room_type(query_params.get("room_type"))
    target_id = _parse_target_id(query_params.get("target_id"))
    thread = _resolve_thread(session, viewer, room_type, target_id, create=False)
    if thread is None:
        return {"thread": None, "messages": [], "has_more": False}
    try:
        after_id = max(0, int(query_params.get("after_id") or 0))
    except (TypeError, ValueError):
        after_id = 0
    query = _message_query_for_viewer(thread, viewer)
    if after_id:
        query = query.filter(id__gt=after_id)
    rows = list(query.order_by("-id")[:100])
    rows.reverse()
    return {
        "thread": _thread_summary(thread, viewer),
        "messages": [
            chat_message_row(message, viewer=viewer, include_moderation=viewer.role == "teacher")
            for message in rows
        ],
        "has_more": query.count() > 100,
    }


def _mark_read(session: ClassroomSession, viewer, data) -> dict:
    room_type = _parse_room_type(data.get("room_type"))
    target_id = _parse_target_id(data.get("target_id"))
    thread = _resolve_thread(session, viewer, room_type, target_id, create=False)
    if thread is None:
        return {"thread_id": None, "last_read_message_id": None}
    try:
        message_id = int(data.get("message_id") or 0)
    except (TypeError, ValueError):
        message_id = 0
    message = _message_query_for_viewer(thread, viewer).filter(id=message_id).first() if message_id else None
    state, _ = ClassroomChatReadState.objects.get_or_create(thread=thread, user=viewer)
    if message is not None and (not state.last_read_message_id or message.id > state.last_read_message_id):
        state.last_read_message = message
        state.save(update_fields=["last_read_message", "last_read_at"])
    return {"thread_id": thread.id, "last_read_message_id": state.last_read_message_id}


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_chat_context(request, pk):
    try:
        return ok(_context_payload(_teacher_session(request, pk), request.user))
    except ChatError as exc:
        return _chat_fail(exc)


@api_view(["PATCH"])
@permission_classes([IsTeacher])
def teacher_chat_settings(request, pk):
    try:
        session = _teacher_session(request, pk)
        if session.status != ClassroomSession.Status.RUNNING:
            raise ChatError("请先开始课堂，再开启聊天。", status=400)
        config = _chat_config(session)
        values = {}
        for field in ("whole_class_enabled", "teacher_private_enabled", "group_chat_enabled"):
            raw = request.data.get(field, getattr(config, field))
            values[field] = raw if isinstance(raw, bool) else str(raw).strip().lower() in {"1", "true", "yes", "on"}
        if values["group_chat_enabled"] and _active_collaboration(session) is None:
            raise ChatError("请先开启并完成课堂分组，再开启小组聊天。", errors={"group_chat_enabled": ["当前没有可用小组。"]})
        for field, value in values.items():
            setattr(config, field, value)
        config.updated_by = request.user
        config.save()
        publish_chat_event(
            [session_group(session.id)],
            {"type": "chat.settings.updated", "session_id": session.id},
        )
        return ok(_context_payload(session, request.user), "聊天设置已更新。")
    except ChatError as exc:
        return _chat_fail(exc)


@api_view(["GET", "POST"])
@permission_classes([IsTeacher])
def teacher_chat_messages(request, pk):
    try:
        session = _teacher_session(request, pk)
        if request.method == "GET":
            return ok(_messages_payload(session, request.user, request.GET))
        room_type = _parse_room_type(request.data.get("room_type"))
        target_id = _parse_target_id(request.data.get("target_id"))
        message = _create_message(session, request.user, room_type, target_id, request.data.get("content"))
        return ok(chat_message_row(message, viewer=request.user, include_moderation=True), "消息已发送。", status=201)
    except ChatError as exc:
        return _chat_fail(exc)


@api_view(["POST"])
@permission_classes([IsTeacher])
def teacher_chat_read(request, pk):
    try:
        return ok(_mark_read(_teacher_session(request, pk), request.user, request.data))
    except ChatError as exc:
        return _chat_fail(exc)


@api_view(["GET"])
@permission_classes([IsTeacher])
def teacher_chat_moderation(request, pk):
    try:
        session = _teacher_session(request, pk)
        status_filter = str(request.GET.get("status") or "pending").strip()
        query = ClassroomChatMessage.objects.filter(thread__session=session, sender__role="student")
        if status_filter == "pending":
            query = query.filter(moderation_status=ClassroomChatMessage.ModerationStatus.PENDING)
        elif status_filter == "reviewed":
            query = query.exclude(review_action=ClassroomChatMessage.ReviewAction.NONE)
        elif status_filter != "all":
            raise ChatError("审核状态筛选不正确。")
        messages = list(query.select_related("thread", "thread__student", "thread__group", "sender", "reviewed_by").order_by("-created_at")[:100])
        return ok(
            {
                "count": len(messages),
                "results": [chat_message_row(message, viewer=request.user, include_moderation=True) for message in messages],
            }
        )
    except ChatError as exc:
        return _chat_fail(exc)


@api_view(["POST"])
@permission_classes([IsTeacher])
@transaction.atomic
def teacher_chat_moderate(request, pk, message_id):
    try:
        session = _teacher_session(request, pk)
        message = (
            ClassroomChatMessage.objects.select_for_update(of=("self",))
            .select_related("thread", "thread__student", "thread__group", "sender", "reviewed_by")
            .filter(pk=message_id, thread__session=session, sender__role="student")
            .first()
        )
        if message is None:
            raise ChatError("聊天消息不存在或无权处理。", status=404)
        if message.review_action != ClassroomChatMessage.ReviewAction.NONE:
            raise ChatError("该消息已经处理，不能重复审核或扣分。", status=409)
        action = str(request.data.get("action") or "").strip()
        if action not in {item.value for item in ClassroomChatMessage.ReviewAction if item.value != "none"}:
            raise ChatError("请选择放行、警告、撤回或扣分。", errors={"action": ["处理方式不正确。"]})
        note = str(request.data.get("note") or "").strip()[:255]
        points = 0.0
        if action == ClassroomChatMessage.ReviewAction.DEDUCT:
            raw_points = request.data.get("points", DEFAULT_DEDUCTION.get(message.severity, 1.0))
            try:
                points = round(float(raw_points), 1)
            except (TypeError, ValueError):
                raise ChatError("扣分分值不正确。", errors={"points": ["请输入有效分值。"]})
            if points <= 0 or points > 100:
                raise ChatError("扣分分值应大于 0 且不超过 100。", errors={"points": ["请输入 0-100 之间的正数。"]})

        message.review_action = action
        message.review_note = note
        message.deduction_points = points
        message.reviewed_by = request.user
        message.reviewed_at = timezone.now()
        message.moderation_status = (
            ClassroomChatMessage.ModerationStatus.VISIBLE
            if action == ClassroomChatMessage.ReviewAction.ALLOW
            else ClassroomChatMessage.ModerationStatus.REMOVED
        )
        event_metadata = {
            "action": "classroom_chat_moderation",
            "classroom_session": session.id,
            "thread": message.thread_id,
            "room_type": message.thread.room_type,
            "moderation_action": action,
            "severity": message.severity,
            "reviewed_by": request.user.id,
            "deduction_points": points,
            "review_note": note,
        }
        try:
            if points:
                profile = (
                    StudentProfile.objects.select_related("user", "class_group")
                    .filter(user=message.sender)
                    .first()
                )
                if profile is None:
                    raise ChatError("学生档案不存在，无法扣分。", status=404)
                record_classroom_point_adjustment(
                    teacher=request.user,
                    student_profile=profile,
                    classroom_session=session,
                    object_type="classroom_chat_message",
                    object_id=message.id,
                    reason_code="chat_moderation_deduction",
                    requested_score=-points,
                    legacy_metadata=event_metadata,
                    insufficient_policy="reject",
                    occurred_at=message.reviewed_at,
                )
            else:
                intensity = (
                    "high"
                    if message.severity == ClassroomChatMessage.Severity.SEVERE
                    else "medium"
                    if message.severity == ClassroomChatMessage.Severity.MODERATE
                    else "low"
                )
                record_learning_event(
                    actor=request.user,
                    target_student=message.sender,
                    event_name="intervention.created",
                    payload={
                        "intervention_type": "chat_moderation",
                        "reason_code": f"chat_moderation_{action}",
                        "intensity": intensity,
                    },
                    legacy_event_type=LearningEvent.EventType.TEACHER_INTERVENTION,
                    legacy_actor=message.sender,
                    class_group=session.class_group,
                    subject=session.course.subject,
                    course=session.course,
                    lesson=session.lesson,
                    classroom_session=session,
                    object_type="classroom_chat_message",
                    object_id=message.id,
                    legacy_score=0,
                    legacy_metadata=event_metadata,
                    occurred_at=message.reviewed_at,
                )
        except EventWriteError as exc:
            raise ChatError(exc.message) from exc

        message.save(
            update_fields=[
                "review_action",
                "review_note",
                "deduction_points",
                "reviewed_by",
                "reviewed_at",
                "moderation_status",
                "updated_at",
            ]
        )
        _push_changed(message, event_type="chat.message.reviewed")
        return ok(chat_message_row(message, viewer=request.user, include_moderation=True), "消息已处理。")
    except ChatError as exc:
        return _chat_fail(exc)


@api_view(["GET"])
@permission_classes([IsStudent])
def student_chat_context(request, pk):
    try:
        session, _ = _student_session(request, pk)
        return ok(_context_payload(session, request.user))
    except ChatError as exc:
        return _chat_fail(exc)


@api_view(["GET", "POST"])
@permission_classes([IsStudent])
def student_chat_messages(request, pk):
    try:
        session, _ = _student_session(request, pk)
        if request.method == "GET":
            return ok(_messages_payload(session, request.user, request.GET))
        room_type = _parse_room_type(request.data.get("room_type"))
        target_id = _parse_target_id(request.data.get("target_id"))
        message = _create_message(session, request.user, room_type, target_id, request.data.get("content"))
        text = "消息已进入教师审核。" if message.moderation_status == "pending" else "消息已发送。"
        return ok(chat_message_row(message, viewer=request.user), text, status=201)
    except ChatError as exc:
        return _chat_fail(exc)


@api_view(["POST"])
@permission_classes([IsStudent])
def student_chat_read(request, pk):
    try:
        session, _ = _student_session(request, pk)
        return ok(_mark_read(session, request.user, request.data))
    except ChatError as exc:
        return _chat_fail(exc)


@api_view(["POST"])
@permission_classes([IsStudent])
@transaction.atomic
def student_chat_moderation_feedback_ack(request, pk, message_id):
    try:
        session, profile = _student_session(request, pk)
        message = ClassroomChatMessage.objects.filter(
            pk=message_id,
            thread__session=session,
            sender=request.user,
            moderation_status=ClassroomChatMessage.ModerationStatus.REMOVED,
            review_action__in=[
                ClassroomChatMessage.ReviewAction.WARN,
                ClassroomChatMessage.ReviewAction.REMOVE,
                ClassroomChatMessage.ReviewAction.DEDUCT,
            ],
        ).first()
        if message is None:
            raise ChatError("处理反馈不存在或无权确认。", status=404)
        exists = LearningEvent.objects.filter(
            actor=request.user,
            object_type="classroom_chat_message",
            object_id=str(message.id),
            metadata__action="classroom_chat_moderation_feedback_ack",
        ).exists()
        if not exists:
            try:
                record_intervention_acknowledged(
                    student=request.user,
                    profile=profile,
                    session=session,
                    object_type="classroom_chat_message",
                    object_id=message.id,
                    intervention_type="chat_moderation",
                    action=message.review_action,
                    points=message.deduction_points,
                    legacy_metadata={
                        "action": "classroom_chat_moderation_feedback_ack",
                        "classroom_session": session.id,
                        "moderation_action": message.review_action,
                        "deduction_points": message.deduction_points,
                    },
                )
            except EventWriteError as exc:
                raise ChatError(exc.message, status=500) from exc
        return ok({"message_id": message.id, "acknowledged": True}, "处理反馈已确认。")
    except ChatError as exc:
        return _chat_fail(exc)
