from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import Max, Q
from django.db import transaction
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from aiops.crypto import decrypt_secret, encrypt_secret
from aiops.models import TeacherAIProvider
from courses.models import (
    ClassroomActivity,
    ClassroomGroupCollaboration,
    ClassroomSession,
    Course,
    CourseClass,
    LearningWebPage,
    Lesson,
    LessonStep,
    Resource,
    ResourceFile,
    Subject,
)
from learning.models import (
    Feedback,
    LearningEvent,
    Notice,
    PretestPaper,
    PretestQuestion,
)
from learning_analytics.services.classroom_events import (
    ClassroomEventError,
    release_classroom_step_opportunities,
    withdraw_classroom_step_opportunities,
)
from learning_analytics.services.attendance_events import (
    AttendanceEventError,
    release_attendance_opportunities,
    withdraw_attendance_opportunities,
)
from learning_analytics.services.classroom_interaction_events import (
    ClassroomInteractionEventError,
    record_random_call_selected,
    release_quick_answer_opportunities,
    withdraw_quick_answer_opportunities,
)
from learning_analytics.services.evaluation_events import (
    EvaluationEventError,
    withdraw_classroom_evaluation_opportunities,
)
from learning_analytics.services.group_collaboration_events import (
    GroupCollaborationEventError,
    withdraw_group_collaboration_opportunities,
)
from learning_analytics.services.dual_write import EventWriteError
from learning_analytics.services.operational_events import (
    record_classroom_control_executed,
)
from ops.forms import PASSWORD_PATTERN, _matches
from ops.forms import (
    PERSON_NAME_PATTERN,
    PHONE_PATTERN,
    SchoolAdminCreateForm,
    SchoolAdminUpdateForm,
    SchoolForm,
)
from ops.models import AuditLog
from ops.xlsx import normalize_text, read_table_rows
from school.models import ClassGroup, School, StudentProfile, TeachingAssignment
from school_admin.forms import TeacherCreateForm, TeacherUpdateForm
from ops.forms import TEACHING_PASSWORD_PATTERN
from .protected_files import protected_file_url
from .serializers import clean_resource_ext

USERNAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{4,31}$"
CLASS_NAME_PATTERN = r"^[\u4e00-\u9fa5A-Za-z0-9（）()·\-\s]{1,64}$"
GRADE_PATTERN = r"^[\u4e00-\u9fa5A-Za-z0-9届级年高初小\s\-]{0,32}$"
STUDENT_NO_PATTERN = r"^[A-Za-z0-9_-]{0,32}$"
SUBJECT_CODE_PATTERN = r"^[A-Z0-9][A-Z0-9_-]{1,31}$"
COURSE_TITLE_PATTERN = r"^[\u4e00-\u9fa5A-Za-z0-9（）()·《》：:，,。\.\-\s]{2,128}$"
RESOURCE_TITLE_PATTERN = r"^[\u4e00-\u9fa5A-Za-z0-9（）()·《》：:，,。\._\-\s]{2,128}$"
BULK_LIMIT = 200
COURSE_COVER_MAX_SIZE = 5 * 1024 * 1024
COURSE_COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
COURSE_COVER_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
RESOURCE_MAX_SIZE = 512 * 1024 * 1024
RESOURCE_ALLOWED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".bmp",
    ".svg",
    ".mp4",
    ".webm",
    ".mov",
    ".ogg",
    ".mp3",
    ".wav",
    ".m4a",
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".csv",
    ".txt",
    ".md",
    ".rtf",
    ".html",
    ".css",
    ".js",
    ".json",
    ".xml",
    ".py",
    ".java",
    ".c",
    ".cpp",
    ".zip",
    ".rar",
    ".7z",
}
CLASSROOM_COMMANDS = {
    "sign_in": {
        "activity_type": ClassroomActivity.ActivityType.SIGN_IN,
        "title": "课堂签到",
    },
    "random_pick": {
        "activity_type": ClassroomActivity.ActivityType.QUESTION,
        "title": "随机点名",
    },
    "quick_answer": {
        "activity_type": ClassroomActivity.ActivityType.QUICK_ANSWER,
        "title": "抢答",
    },
    "timer": {
        "activity_type": ClassroomActivity.ActivityType.TASK,
        "title": "课堂倒计时",
    },
    "broadcast": {
        "activity_type": ClassroomActivity.ActivityType.BROADCAST,
        "title": "课堂广播",
    },
}
LESSON_QUESTION_TYPES = {"single", "multiple", "judge", "blank", "text", "file"}
LESSON_QUESTION_TYPE_LABELS = {
    "single": "单选",
    "multiple": "多选",
    "judge": "判断",
    "blank": "填空",
    "text": "简答",
    "file": "附件提交",
}
LESSON_TARGET_LAYER_VALUES = {item.value for item in LessonStep.TargetLayer}
LESSON_FILE_DEFAULT_EXTENSIONS = [
    "doc",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "pdf",
    "zip",
    "rar",
    "7z",
    "png",
    "jpg",
    "jpeg",
]
LESSON_FILE_ALLOWED_EXTENSIONS = set(
    LESSON_FILE_DEFAULT_EXTENSIONS
    + ["webp", "gif", "mp4", "webm", "mov", "mp3", "wav", "csv", "txt", "md"]
)
AI_LAYER_TARGETS = ("A", "B", "C", "A/B", "B/C")
CLASSROOM_EVALUATION_TYPES = ("self", "peer", "teacher")
LEARNING_PAGE_BLOCK_TYPES = {
    "content",
    "callout",
    "list",
    "steps",
    "cards",
    "table",
    "code",
    "visualization",
    "interactive",
    "form",
}
LEARNING_PAGE_FIELD_TYPES = {
    "single",
    "multiple",
    "select",
    "short_text",
    "long_text",
    "number",
    "scale",
}
LEARNING_PAGE_ACCENTS = {"blue", "green", "cyan", "amber", "red", "indigo"}
LEARNING_PAGE_VISUALIZATION_TYPES = {"process", "timeline", "bars", "binary"}
LEARNING_PAGE_VISUALIZATION_TONES = {"blue", "green", "cyan", "amber", "red", "indigo"}
LEARNING_PAGE_GENERATION_MODES = {"auto", "interactive", "structured"}
TEACHER_IMPORT_HEADERS = ["登录账号", "姓名", "联系电话", "初始密码", "状态"]
STUDENT_IMPORT_HEADERS = [
    "登录账号",
    "姓名",
    "学号",
    "班级",
    "联系电话",
    "初始密码",
    "层级",
    "小组号",
    "积分",
    "状态",
]
DEFAULT_AI_BASE_URL = "https://api.deepseek.com"
DEFAULT_AI_MODEL = "deepseek-v4-flash"
AI_MODEL_PATTERN = r"^[A-Za-z0-9._:\-]{2,64}$"
AI_KEY_PATTERN = r"^\S{10,512}$"

# Pretest and question-bank domain services extracted from api.services.
from . import services as _shared_services
from .services import (
    QUESTION_BANK_AI_DIFFICULTIES,
    QUESTION_BANK_AI_TYPES,
    ServiceError,
    _call_teacher_chat_json,
    _clean_bool,
    _clean_float,
    _clean_optional_int,
    _fullmatch,
    _lesson_question_base_score,
    write_audit,
)

def _initial_layer_scores(
    base_score: float, target_layer: str, *, difficulty: str = "normal"
) -> dict[str, float]:
    scores = {"A": base_score, "B": base_score, "C": base_score}
    if difficulty == "extension":
        scores["A"] = min(base_score + 1, 100)
    elif difficulty == "support":
        scores["C"] = max(base_score - 0.5, 0)
    if target_layer == "A":
        scores["A"] = min(base_score + 1, 100)
    elif target_layer == "C":
        scores["C"] = max(base_score - 0.5, 0)
    elif target_layer == "A/B":
        scores["A"] = min(base_score + 0.5, 100)
    elif target_layer == "B/C":
        scores["C"] = max(base_score - 0.5, 0)
    return scores


def _clean_ai_generated_questions(
    raw_questions, *, requested_count: int, fallback_type: str, fallback_layer: str
) -> list[dict]:
    if not isinstance(raw_questions, list):
        return []
    cleaned: list[dict] = []
    for index, raw_item in enumerate(raw_questions[: min(requested_count, 10)]):
        if not isinstance(raw_item, dict):
            continue
        question_type = str(
            raw_item.get("question_type") or fallback_type or "single"
        ).strip()
        if question_type not in LESSON_QUESTION_TYPES:
            question_type = (
                fallback_type if fallback_type in LESSON_QUESTION_TYPES else "single"
            )
        stem = normalize_text(str(raw_item.get("stem") or ""))
        if len(stem) < 2:
            continue
        stem = stem[:1000]
        target_layer = str(
            raw_item.get("target_layer") or fallback_layer or "all"
        ).strip()
        if target_layer not in LESSON_TARGET_LAYER_VALUES:
            target_layer = (
                fallback_layer
                if fallback_layer in LESSON_TARGET_LAYER_VALUES
                else "all"
            )
        use_layer_scores = _clean_bool(
            raw_item.get("use_layer_scores", target_layer == "A/B/C")
        )

        options: list[str] = []
        if question_type == "judge":
            options = ["正确", "错误"]
        elif question_type in {"single", "multiple"}:
            raw_options = raw_item.get("options")
            if isinstance(raw_options, list):
                for option in raw_options:
                    text = normalize_text(str(option))[:200]
                    if text and text not in options:
                        options.append(text)
            if len(options) < 2:
                continue
            options = options[:8]

        raw_answer = raw_item.get("answer", [])
        if isinstance(raw_answer, list):
            answer = [
                normalize_text(str(value))
                for value in raw_answer
                if normalize_text(str(value))
            ]
        elif raw_answer:
            answer = [normalize_text(str(raw_answer))]
        else:
            answer = []
        if question_type == "single" and answer:
            answer = answer[:1]
        if question_type == "judge":
            answer = answer[:1] if answer and answer[0] in {"正确", "错误"} else []
        if question_type in {"single", "multiple"} and answer:
            answer = [value for value in answer if value in options]

        try:
            base_score = float(
                raw_item.get("score") or _lesson_question_base_score(question_type)
            )
        except (TypeError, ValueError):
            base_score = _lesson_question_base_score(question_type)
        base_score = min(max(base_score, 0), 100)

        raw_layer_scores = (
            raw_item.get("layer_scores")
            if isinstance(raw_item.get("layer_scores"), dict)
            else {}
        )
        initial_scores = _initial_layer_scores(
            base_score,
            target_layer,
            difficulty=str(raw_item.get("difficulty") or "normal"),
        )
        layer_scores = {}
        for layer in ("A", "B", "C"):
            try:
                value = float(raw_layer_scores.get(layer, initial_scores[layer]))
            except (TypeError, ValueError):
                value = initial_scores[layer]
            layer_scores[layer] = min(max(value, 0), 100)

        cleaned.append(
            {
                "id": f"q_{uuid4().hex[:12]}",
                "question_type": question_type,
                "stem": stem,
                "options": options,
                "answer": answer,
                "score": base_score,
                "target_layer": target_layer,
                "use_layer_scores": use_layer_scores and target_layer != "all",
                "layer_scores": layer_scores,
                "analysis": normalize_text(str(raw_item.get("analysis") or ""))[:1000],
                "is_required": _clean_bool(raw_item.get("is_required", True)),
                "sort_order": (index + 1) * 10,
                "ai_generated": True,
                "ai_score_note": normalize_text(
                    str(
                        raw_item.get("score_note")
                        or "AI 建议分值，教师确认后才写入环节。"
                    )
                )[:300],
            }
        )
    return cleaned


def generate_lesson_step_questions_with_ai(request, data) -> dict:
    direction = normalize_text(str(data.get("direction") or ""))
    question_type = str(data.get("question_type") or "single").strip()
    layer_targets = list(AI_LAYER_TARGETS)
    raw_count = data.get("count", 3)
    try:
        count = int(raw_count)
    except (TypeError, ValueError):
        count = 0
    lesson_title = normalize_text(str(data.get("lesson_title") or ""))
    step_title = normalize_text(str(data.get("step_title") or ""))
    subject_name = normalize_text(str(data.get("subject_name") or ""))
    student_instruction = normalize_text(str(data.get("student_instruction") or ""))
    requirement = normalize_text(str(data.get("requirement") or ""))

    errors: dict[str, list[str]] = {}
    if question_type not in LESSON_QUESTION_TYPES:
        errors["question_type"] = ["题型不正确。"]
    if count < 1 or count > 10:
        errors["count"] = ["每组题目数量需为 1-10。"]
    if len(direction) < 4 or len(direction) > 1000:
        errors["direction"] = ["出题方向需为 4-1000 个字符。"]
    if len(requirement) > 1000:
        errors["requirement"] = ["补充要求不能超过 1000 个字符。"]
    if errors:
        raise ServiceError("AI 出题参数校验失败。", errors=errors, status=400)

    base_score = _lesson_question_base_score(question_type)
    score_defaults = {
        target: {
            "base_score": base_score,
            "layer_scores": _initial_layer_scores(base_score, target),
        }
        for target in layer_targets
    }
    system_prompt = (
        "你是 STRATA 数智教学系统的教师备课助手。"
        "你只能生成结构化课堂题草稿，不能生成代码、网页脚本或外链。"
        "输出必须是严格 JSON 对象，不能包含 Markdown。"
    )
    user_prompt = f"""
请按同一个出题方向，同时生成 A、B、C、A/B、B/C 五组分层课堂题草稿，每组 {count} 道题。请严格返回 JSON：
{{
  "groups": [
    {{
      "target_layer": "A",
      "questions": [
        {{
          "question_type": "{question_type}",
          "stem": "题干",
          "options": ["选项1", "选项2"],
          "answer": ["参考答案"],
          "score": {base_score},
          "target_layer": "A",
          "use_layer_scores": true,
          "layer_scores": {json.dumps(score_defaults["A"]["layer_scores"], ensure_ascii=False)},
          "analysis": "解析或评分说明",
          "is_required": true,
          "difficulty": "extension",
          "score_note": "分值建议理由"
        }}
      ]
    }}
  ]
}}

课程/学科信息：
- 学科：{subject_name or "未提供"}
- 课时：{lesson_title or "未提供"}
- 当前环节：{step_title or "未提供"}
- 学生可见说明：{student_instruction or "未提供"}

出题方向：
{direction}

补充要求：
{requirement or "无"}

规则：
1. 题型只能是 {question_type}。
2. 必须生成 5 个 group，target_layer 分别为 A、B、C、A/B、B/C，不要生成 all 或 A/B/C。
3. 每个 group 必须有 {count} 道题，组内每道题的 target_layer 必须等于该组 target_layer。
4. A 题偏拓展提升，B 题偏核心达成，C 题偏基础支架，A/B 题用于核心加拓展，B/C 题用于基础巩固和支架。
5. 单选/多选至少 4 个选项；判断题 options 固定为 ["正确","错误"]；填空和简答不需要 options。
6. answer 必须是数组；单选和判断只给 1 个答案。
7. 分值先给建议值，教师会确认或修改。基础分用 {base_score}，各组默认分值参考：{json.dumps(score_defaults, ensure_ascii=False)}。
8. 语言简洁，贴近高中课堂，避免空泛 AI 味表述。
""".strip()
    payload = _shared_services._call_teacher_chat_json(
        request, system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=5200
    )
    raw_groups = payload.get("groups")
    groups: list[dict] = []
    questions: list[dict] = []
    if isinstance(raw_groups, list):
        by_target = {
            str(group.get("target_layer") or ""): group.get("questions")
            for group in raw_groups
            if isinstance(group, dict)
        }
    else:
        by_target = {}
    for target in layer_targets:
        raw_questions = by_target.get(target, [])
        group_questions = _clean_ai_generated_questions(
            raw_questions,
            requested_count=count,
            fallback_type=question_type,
            fallback_layer=target,
        )
        for index, question in enumerate(group_questions, start=1):
            question["target_layer"] = target
            question["use_layer_scores"] = True
            question["layer_scores"] = (
                question.get("layer_scores") or score_defaults[target]["layer_scores"]
            )
            question["sort_order"] = len(questions) * 10 + 10
            question["ai_group_order"] = index
        groups.append(
            {
                "target_layer": target,
                "target_layer_label": target,
                "questions": group_questions,
                "score_defaults": score_defaults[target],
            }
        )
        questions.extend(group_questions)
    if not questions:
        raise ServiceError(
            "AI 没有生成可用题目，请调整出题方向后重试。",
            errors={"ai": ["未得到可用题目。"]},
            status=400,
        )

    _shared_services.write_audit(
        request,
        "teacher.ai_generate_questions",
        school=request.user.school,
        target_type="lesson_step_question",
        detail={
            "question_type": question_type,
            "target_layers": layer_targets,
            "count": len(questions),
            "subject": subject_name,
            "lesson_title": lesson_title,
            "step_title": step_title,
        },
    )
    return {
        "questions": questions,
        "groups": groups,
        "score_defaults": {
            "base_score": base_score,
            "groups": score_defaults,
            "note": "系统按 A、B、C、A/B、B/C 同时给题目和分值建议；后续接入分层模型后，只作为建议，必须由教师确认。",
        },
    }


def _clean_question_bank_ai_drafts(
    raw_questions, *, count: int, fallback_type: str, fallback_difficulty: str
) -> list[dict]:
    if not isinstance(raw_questions, list):
        return []
    drafts = []
    for raw in raw_questions[:count]:
        if not isinstance(raw, dict):
            continue
        question_type = str(raw.get("question_type") or fallback_type).strip().lower()
        if question_type not in QUESTION_BANK_AI_TYPES:
            question_type = (
                fallback_type if fallback_type in QUESTION_BANK_AI_TYPES else "single"
            )
        difficulty = str(raw.get("difficulty") or fallback_difficulty).strip().lower()
        if difficulty not in QUESTION_BANK_AI_DIFFICULTIES:
            difficulty = fallback_difficulty
        stem = normalize_text(str(raw.get("stem") or ""))[:2000]
        if len(stem) < 2:
            continue

        options = []
        if question_type == "judge":
            options = ["正确", "错误"]
        elif question_type in {"single", "multiple"}:
            raw_options = (
                raw.get("options") if isinstance(raw.get("options"), list) else []
            )
            for value in raw_options[:10]:
                text = normalize_text(str(value))[:300]
                if text and text not in options:
                    options.append(text)
            if len(options) < 2:
                continue

        raw_answer = raw.get("answer")
        if isinstance(raw_answer, list):
            answer = [
                normalize_text(str(value))[:500]
                for value in raw_answer
                if normalize_text(str(value))
            ]
        elif isinstance(raw_answer, (str, int, float, bool)) and raw_answer not in {
            None,
            "",
        }:
            answer = [normalize_text(str(raw_answer))[:500]]
        else:
            answer = []
        if question_type in {"single", "judge"}:
            answer = answer[:1]
        if question_type in {"single", "multiple", "judge"}:
            answer = [value for value in answer if value in options]
            if not answer:
                continue
        if question_type == "blank" and not answer:
            continue
        if question_type == "text":
            answer = []

        default_score = _lesson_question_base_score(question_type)
        try:
            default_score = float(
                raw.get("default_score") or raw.get("score") or default_score
            )
        except (TypeError, ValueError):
            pass
        if not math.isfinite(default_score):
            default_score = _lesson_question_base_score(question_type)
        default_score = min(max(default_score, 0.5), 100)
        drafts.append(
            {
                "draft_id": f"ai_{uuid4().hex[:12]}",
                "stem": stem,
                "question_type": question_type,
                "options": options,
                "answer": answer,
                "analysis": normalize_text(str(raw.get("analysis") or ""))[:4000],
                "difficulty": difficulty,
                "knowledge_point": normalize_text(
                    str(raw.get("knowledge_point") or "")
                )[:128],
                "default_score": default_score,
                "selected": True,
            }
        )
    return drafts


def generate_question_bank_drafts_with_ai(request, data, *, subject_name: str) -> dict:
    direction = normalize_text(str(data.get("direction") or ""))
    knowledge_point = normalize_text(str(data.get("knowledge_point") or ""))
    question_type = str(data.get("question_type") or "mixed").strip().lower()
    difficulty = str(data.get("difficulty") or "normal").strip().lower()
    requirement = normalize_text(str(data.get("requirement") or ""))
    try:
        count = int(data.get("count") or 5)
    except (TypeError, ValueError):
        count = 0

    errors: dict[str, list[str]] = {}
    if len(direction) < 4 or len(direction) > 1500:
        errors["direction"] = ["出题方向需为 4-1500 个字符。"]
    if len(knowledge_point) > 128:
        errors["knowledge_point"] = ["知识点不能超过 128 个字符。"]
    if question_type != "mixed" and question_type not in QUESTION_BANK_AI_TYPES:
        errors["question_type"] = ["题型不正确。"]
    if difficulty not in QUESTION_BANK_AI_DIFFICULTIES:
        errors["difficulty"] = ["难度不正确。"]
    if count < 1 or count > 20:
        errors["count"] = ["单次生成数量需为 1-20 道。"]
    if len(requirement) > 1000:
        errors["requirement"] = ["补充要求不能超过 1000 个字符。"]
    if errors:
        raise ServiceError("AI 题库出题参数校验失败。", errors=errors, status=400)

    allowed_types = (
        [question_type]
        if question_type != "mixed"
        else ["single", "multiple", "judge", "blank", "text"]
    )
    type_rule = (
        f"所有题目必须使用 {question_type} 题型。"
        if question_type != "mixed"
        else "在单选、多选、判断、填空、简答中合理混合题型；优先包含可自动判分的客观题。"
    )
    system_prompt = (
        "你是 STRATA 数智教学系统的学校共享题库出题助手。"
        "你只能生成结构化题目草稿，不能输出代码、Markdown、网页、外链或教学说明。"
        "内容必须事实准确、表述清晰、无歧义，并严格返回 JSON 对象。"
    )
    user_prompt = json.dumps(
        {
            "task": f"为{subject_name}共享题库生成 {count} 道题目草稿",
            "subject": subject_name,
            "direction": direction,
            "knowledge_point": knowledge_point,
            "question_type": question_type,
            "difficulty": difficulty,
            "requirement": requirement,
            "allowed_question_types": allowed_types,
            "rules": [
                type_rule,
                "single 和 multiple 必须提供 4 个互不重复的 options；judge 的 options 固定为正确、错误。",
                "answer 必须是数组，内容必须与 options 的完整文本一致；single 和 judge 只能有一个答案。",
                "blank 至少提供一个参考答案；text 的 answer 必须为空数组，并在 analysis 中给出评分要点。",
                "difficulty 只能是 easy、normal、hard；默认使用请求难度，但可在混合题中作少量合理变化。",
                "default_score 为 0.5-100 的数字；客观题建议 2 分、填空题 3 分、简答题 5-10 分。",
                "knowledge_point 应具体，analysis 必须解释答案或提供评分要点。",
                f"必须返回恰好 {count} 道题，不得重复题干或仅替换数字形成低质量重复题。",
            ],
            "response_schema": {
                "questions": [
                    {
                        "question_type": "single",
                        "stem": "题干",
                        "options": ["选项1", "选项2", "选项3", "选项4"],
                        "answer": ["选项1"],
                        "analysis": "答案解析",
                        "difficulty": difficulty,
                        "knowledge_point": knowledge_point or "具体知识点",
                        "default_score": 2,
                    }
                ]
            },
        },
        ensure_ascii=False,
    )
    raw = _shared_services._call_teacher_chat_json(
        request,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=min(max(2800, count * 650), 12000),
    )
    fallback_type = question_type if question_type != "mixed" else "single"
    drafts = _clean_question_bank_ai_drafts(
        raw.get("questions"),
        count=count,
        fallback_type=fallback_type,
        fallback_difficulty=difficulty,
    )
    if not drafts:
        raise ServiceError(
            "AI 没有生成可用题目，请调整出题方向后重试。",
            errors={"ai": ["生成结果未通过题型、选项和答案校验。"]},
            status=400,
        )
    _shared_services.write_audit(
        request,
        "teacher.question_bank.ai_generate",
        school=request.user.school,
        target_type="question_bank_draft",
        detail={
            "subject": subject_name,
            "question_type": question_type,
            "difficulty": difficulty,
            "requested_count": count,
            "valid_count": len(drafts),
        },
    )
    return {"questions": drafts, "requested_count": count, "valid_count": len(drafts)}


def _school_subject(request, subject_id, errors: dict) -> Subject | None:
    try:
        return Subject.objects.get(pk=subject_id, school=request.user.school)
    except (Subject.DoesNotExist, TypeError, ValueError):
        errors["subject"] = ["请选择本校学科。"]
        return None


def save_pretest_paper(
    request, data, *, paper: PretestPaper | None = None
) -> PretestPaper:
    errors: dict[str, list[str]] = {}
    subject = _school_subject(request, data.get("subject"), errors)
    title = str(data.get("title", "")).strip()
    kind = str(data.get("kind", "")).strip()
    status = (
        str(data.get("status", PretestPaper.Status.DRAFT)).strip()
        or PretestPaper.Status.DRAFT
    )
    introduction = str(data.get("introduction", "")).strip()
    version = _clean_optional_int(
        data.get("version"), "version", errors, min_value=1, max_value=999
    )
    if not _fullmatch(r"^[\u4e00-\u9fa5A-Za-z0-9（）()·\-\s]{2,128}$", title):
        errors["title"] = ["套卷名称需为 2-128 位，可包含中文、字母和数字。"]
    if kind not in {item.value for item in PretestPaper.Kind}:
        errors["kind"] = ["前测类型只能为素养测试或学习态度问卷。"]
    if status not in {item.value for item in PretestPaper.Status}:
        errors["status"] = ["状态只能为草稿、已发布或归档。"]

    if subject and kind and version is None:
        max_version = (
            PretestPaper.objects.filter(
                school=request.user.school, subject=subject, kind=kind
            )
            .aggregate(value=Max("version"))
            .get("value")
            or 0
        )
        version = max_version + 1

    if subject and kind and version:
        queryset = PretestPaper.objects.filter(
            school=request.user.school, subject=subject, kind=kind, version=version
        )
        if paper is not None:
            queryset = queryset.exclude(pk=paper.pk)
        if queryset.exists():
            errors["version"] = ["该学科和前测类型下已存在相同版本号。"]

    if errors:
        raise ServiceError("前测套卷信息校验失败。", errors=errors, status=400)

    is_create = paper is None
    if paper is None:
        paper = PretestPaper(school=request.user.school, created_by=request.user)
    paper.subject = subject
    paper.title = title
    paper.kind = kind
    paper.version = version or 1
    paper.introduction = introduction
    paper.status = status
    if status == PretestPaper.Status.PUBLISHED and paper.published_at is None:
        paper.published_at = timezone.now()
    paper.save()

    if paper.status == PretestPaper.Status.PUBLISHED:
        PretestPaper.objects.filter(
            school=request.user.school,
            subject=paper.subject,
            kind=paper.kind,
            status=PretestPaper.Status.PUBLISHED,
        ).exclude(pk=paper.pk).update(status=PretestPaper.Status.ARCHIVED)

    _shared_services.write_audit(
        request,
        "pretest_paper.create" if is_create else "pretest_paper.update",
        school=request.user.school,
        target_type="pretest_paper",
        target_id=paper.id,
        detail={
            "title": paper.title,
            "subject": paper.subject.code,
            "kind": paper.kind,
            "status": paper.status,
        },
    )
    return paper


def publish_pretest_paper(request, paper: PretestPaper) -> PretestPaper:
    if not paper.questions.exists():
        raise ServiceError("套卷至少需要 1 道题目后才能发布。", status=400)
    paper.status = PretestPaper.Status.PUBLISHED
    paper.published_at = timezone.now()
    paper.save(update_fields=["status", "published_at", "updated_at"])
    PretestPaper.objects.filter(
        school=paper.school,
        subject=paper.subject,
        kind=paper.kind,
        status=PretestPaper.Status.PUBLISHED,
    ).exclude(pk=paper.pk).update(status=PretestPaper.Status.ARCHIVED)
    _shared_services.write_audit(
        request,
        "pretest_paper.publish",
        school=request.user.school,
        target_type="pretest_paper",
        target_id=paper.id,
        detail={
            "title": paper.title,
            "subject": paper.subject.code,
            "kind": paper.kind,
        },
    )
    return paper


def archive_pretest_paper(request, paper: PretestPaper) -> PretestPaper:
    paper.status = PretestPaper.Status.ARCHIVED
    paper.save(update_fields=["status", "updated_at"])
    _shared_services.write_audit(
        request,
        "pretest_paper.archive",
        school=request.user.school,
        target_type="pretest_paper",
        target_id=paper.id,
        detail={
            "title": paper.title,
            "subject": paper.subject.code,
            "kind": paper.kind,
        },
    )
    return paper


def delete_pretest_paper(request, paper: PretestPaper) -> None:
    if paper.status == PretestPaper.Status.PUBLISHED:
        raise ServiceError("已发布前测不能直接删除，请先归档。", status=400)
    if paper.submissions.exists():
        raise ServiceError(
            "该套卷已有学生作答，不能物理删除；请保持归档状态。", status=400
        )
    detail = {"title": paper.title, "subject": paper.subject.code, "kind": paper.kind}
    target_id = paper.id
    paper.delete()
    _shared_services.write_audit(
        request,
        "pretest_paper.delete",
        school=request.user.school,
        target_type="pretest_paper",
        target_id=target_id,
        detail=detail,
    )


def _clean_options(raw_options) -> list[dict]:
    if isinstance(raw_options, list):
        options = []
        for index, option in enumerate(raw_options):
            if isinstance(option, dict):
                label = str(option.get("label") or chr(65 + index)).strip().upper()
                text = str(option.get("text") or "").strip()
            else:
                label = chr(65 + index)
                text = str(option).strip()
            if text:
                options.append({"label": label[:8], "text": text})
        return options
    if isinstance(raw_options, str):
        options = []
        for index, line in enumerate(raw_options.splitlines()):
            text = line.strip()
            if text:
                options.append({"label": chr(65 + index), "text": text})
        return options
    return []


def _clean_answer(raw_answer) -> list[str]:
    if isinstance(raw_answer, list):
        return [str(item).strip().upper() for item in raw_answer if str(item).strip()]
    text = str(raw_answer or "").strip().upper()
    if not text:
        return []
    return [item.strip() for item in re.split(r"[,，\s]+", text) if item.strip()]


def save_pretest_question(
    request, paper: PretestPaper, data, *, question: PretestQuestion | None = None
) -> PretestQuestion:
    errors: dict[str, list[str]] = {}
    stem = str(data.get("stem", "")).strip()
    question_type = str(
        data.get("question_type", PretestQuestion.QuestionType.SINGLE)
    ).strip()
    options = _clean_options(data.get("options", []))
    answer = _clean_answer(data.get("answer", []))
    score = _clean_float(data.get("score"), "score", errors, default=0)
    dimension = str(data.get("dimension", "")).strip()
    sort_order = _clean_optional_int(
        data.get("sort_order"), "sort_order", errors, min_value=0, max_value=9999
    )
    is_required = _clean_bool(data.get("is_required", True))

    if len(stem) < 2:
        errors["stem"] = ["题干不能为空，且至少 2 个字符。"]
    if question_type not in {item.value for item in PretestQuestion.QuestionType}:
        errors["question_type"] = ["题型不正确。"]
    if question_type in {
        PretestQuestion.QuestionType.SINGLE,
        PretestQuestion.QuestionType.MULTIPLE,
        PretestQuestion.QuestionType.SCALE,
    }:
        if len(options) < 2:
            errors["options"] = ["选择题或量表题至少需要 2 个选项。"]
    if question_type == PretestQuestion.QuestionType.SINGLE and len(answer) > 1:
        errors["answer"] = ["单选题只能设置一个正确答案。"]
    if dimension and not _fullmatch(
        r"^[\u4e00-\u9fa5A-Za-z0-9（）()·\-\s]{1,64}$", dimension
    ):
        errors["dimension"] = ["维度名称格式不正确。"]

    valid_labels = {option["label"].upper() for option in options}
    invalid_answers = [
        item for item in answer if valid_labels and item not in valid_labels
    ]
    if invalid_answers:
        errors["answer"] = [f"答案不在选项中：{', '.join(invalid_answers)}。"]

    if errors:
        raise ServiceError("前测题目信息校验失败。", errors=errors, status=400)

    is_create = question is None
    if question is None:
        question = PretestQuestion(paper=paper)
    question.stem = stem
    question.question_type = question_type
    question.options = options
    question.answer = answer
    question.score = score
    question.dimension = dimension
    question.sort_order = sort_order or 0
    question.is_required = is_required
    question.save()
    _shared_services.write_audit(
        request,
        "pretest_question.create" if is_create else "pretest_question.update",
        school=request.user.school,
        target_type="pretest_question",
        target_id=question.id,
        detail={
            "paper": paper.id,
            "type": question.question_type,
            "score": question.score,
        },
    )
    return question


def delete_pretest_question(request, question: PretestQuestion) -> None:
    paper = question.paper
    if paper.status == PretestPaper.Status.PUBLISHED and paper.submissions.exists():
        raise ServiceError(
            "已发布且已有作答记录的题目不能物理删除，请复制新版本套卷后调整。",
            status=400,
        )
    detail = {"paper": paper.id, "stem": question.stem[:80]}
    target_id = question.id
    question.delete()
    _shared_services.write_audit(
        request,
        "pretest_question.delete",
        school=request.user.school,
        target_type="pretest_question",
        target_id=target_id,
        detail=detail,
    )
