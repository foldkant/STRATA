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

# Courses domain services extracted from api.services.
from . import services as _shared_services
from .services import (
    ServiceError,
    _call_teacher_chat_json,
    _clean_bool,
    _clean_optional_int,
    _fullmatch,
    _lesson_question_base_score,
    _teacher_class_groups,
    _validate_course_cover,
    write_audit,
)

def _learning_page_text(value, max_length: int) -> str:
    return normalize_text(str(value or ""))[:max_length]


def _learning_page_identifier(value, *, prefix: str, index: int, seen: set[str]) -> str:
    identifier = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())[:64].strip(
        "_"
    )
    if not identifier or identifier in seen:
        identifier = f"{prefix}_{index}"
    suffix = 2
    candidate = identifier
    while candidate in seen:
        candidate = f"{identifier}_{suffix}"[:64]
        suffix += 1
    seen.add(candidate)
    return candidate


def clean_learning_web_page_schema(
    raw_schema, *, fallback_title: str = "学习任务单"
) -> dict:
    if not isinstance(raw_schema, dict):
        raise ServiceError(
            "AI 学习网页格式不正确，请重试。",
            errors={"schema": ["返回值不是 JSON 对象。"]},
            status=400,
        )

    title = (
        _learning_page_text(raw_schema.get("title") or fallback_title, 128)
        or fallback_title
    )
    subtitle = _learning_page_text(raw_schema.get("subtitle"), 240)
    accent = str(raw_schema.get("accent") or "blue").strip().lower()
    if accent not in LEARNING_PAGE_ACCENTS:
        accent = "blue"
    raw_blocks = raw_schema.get("blocks")
    if not isinstance(raw_blocks, list):
        raw_blocks = []

    blocks: list[dict] = []
    block_ids: set[str] = set()
    form_ids: set[str] = set()
    total_fields = 0
    interactive_blocks = 0
    for index, raw_block in enumerate(raw_blocks[:30], start=1):
        if not isinstance(raw_block, dict):
            continue
        block_type = str(raw_block.get("type") or "content").strip().lower()
        if block_type in {"animation", "animated_visualization", "visual"}:
            block_type = "visualization"
        if block_type in {
            "html_animation",
            "web_animation",
            "interactive_animation",
            "simulation",
        }:
            block_type = "interactive"
        if block_type not in LEARNING_PAGE_BLOCK_TYPES:
            continue
        block = {
            "id": _learning_page_identifier(
                raw_block.get("id"), prefix="block", index=index, seen=block_ids
            ),
            "type": block_type,
            "title": _learning_page_text(raw_block.get("title"), 120),
        }
        if block_type in {"content", "callout"}:
            block["body"] = _learning_page_text(
                raw_block.get("body") or raw_block.get("content"), 5000
            )
            if block_type == "callout":
                tone = str(raw_block.get("tone") or "info").strip().lower()
                block["tone"] = (
                    tone if tone in {"info", "success", "warning", "danger"} else "info"
                )
        elif block_type == "list":
            raw_items = (
                raw_block.get("items")
                if isinstance(raw_block.get("items"), list)
                else []
            )
            block["items"] = [
                _learning_page_text(item, 500)
                for item in raw_items[:30]
                if _learning_page_text(item, 500)
            ]
        elif block_type in {"steps", "cards"}:
            raw_items = (
                raw_block.get("items")
                if isinstance(raw_block.get("items"), list)
                else []
            )
            item_rows = []
            for raw_item in raw_items[:20]:
                if not isinstance(raw_item, dict):
                    continue
                item_title = _learning_page_text(raw_item.get("title"), 120)
                item_body = _learning_page_text(
                    raw_item.get("body") or raw_item.get("description"), 1200
                )
                if item_title or item_body:
                    item_rows.append({"title": item_title, "body": item_body})
            block["items"] = item_rows
        elif block_type == "table":
            raw_headers = (
                raw_block.get("headers")
                if isinstance(raw_block.get("headers"), list)
                else []
            )
            headers = [_learning_page_text(item, 100) for item in raw_headers[:8]]
            raw_rows = (
                raw_block.get("rows") if isinstance(raw_block.get("rows"), list) else []
            )
            rows = []
            for raw_row in raw_rows[:30]:
                if not isinstance(raw_row, list):
                    continue
                rows.append(
                    [
                        _learning_page_text(item, 500)
                        for item in raw_row[: len(headers) or 8]
                    ]
                )
            block["headers"] = headers
            block["rows"] = rows
        elif block_type == "code":
            block["language"] = re.sub(
                r"[^A-Za-z0-9_+.#-]", "", str(raw_block.get("language") or "text")
            )[:24]
            block["code"] = str(raw_block.get("code") or "")[:12000]
        elif block_type == "visualization":
            visualization_type = (
                str(
                    raw_block.get("visualization_type")
                    or raw_block.get("kind")
                    or "process"
                )
                .strip()
                .lower()
            )
            visualization_aliases = {
                "flow": "process",
                "flowchart": "process",
                "sequence": "timeline",
                "bar": "bars",
                "bar_chart": "bars",
                "chart": "bars",
                "binary_stream": "binary",
                "encoding": "binary",
            }
            visualization_type = visualization_aliases.get(
                visualization_type, visualization_type
            )
            if visualization_type not in LEARNING_PAGE_VISUALIZATION_TYPES:
                visualization_type = "process"
            raw_items = (
                raw_block.get("items")
                if isinstance(raw_block.get("items"), list)
                else []
            )
            item_rows = []
            for raw_item in raw_items[:16]:
                if not isinstance(raw_item, dict):
                    continue
                label = _learning_page_text(
                    raw_item.get("label") or raw_item.get("title"), 100
                )
                detail = _learning_page_text(
                    raw_item.get("detail")
                    or raw_item.get("body")
                    or raw_item.get("description"),
                    500,
                )
                code = _learning_page_text(
                    raw_item.get("code") or raw_item.get("token"), 64
                )
                try:
                    value = (
                        float(raw_item.get("value"))
                        if raw_item.get("value") not in {None, ""}
                        else None
                    )
                except (TypeError, ValueError):
                    value = None
                if value is not None:
                    value = min(max(value, 0), 1000000)
                tone = str(raw_item.get("tone") or "blue").strip().lower()
                if tone not in LEARNING_PAGE_VISUALIZATION_TONES:
                    tone = "blue"
                if label or detail or code or value is not None:
                    item_rows.append(
                        {
                            "label": label,
                            "detail": detail,
                            "code": code,
                            "value": value,
                            "tone": tone,
                        }
                    )
            if len(item_rows) < 2:
                continue
            try:
                duration_ms = int(raw_block.get("duration_ms") or 5000)
            except (TypeError, ValueError):
                duration_ms = 5000
            block["visualization_type"] = visualization_type
            block["description"] = _learning_page_text(
                raw_block.get("description") or raw_block.get("body"), 600
            )
            block["duration_ms"] = min(max(duration_ms, 1500), 15000)
            block["autoplay"] = _clean_bool(raw_block.get("autoplay", True))
            block["loop"] = _clean_bool(raw_block.get("loop", False))
            block["items"] = item_rows
        elif block_type == "interactive":
            if interactive_blocks >= 4:
                continue
            html = str(raw_block.get("html") or "")[:30000]
            css = str(raw_block.get("css") or "")[:30000]
            javascript = str(raw_block.get("javascript") or raw_block.get("js") or "")[
                :30000
            ]
            if not html.strip() and not javascript.strip():
                continue
            try:
                height = int(raw_block.get("height") or 520)
            except (TypeError, ValueError):
                height = 520
            block["description"] = _learning_page_text(
                raw_block.get("description"), 600
            )
            block["html"] = html
            block["css"] = css
            block["javascript"] = javascript
            block["height"] = min(max(height, 280), 900)
            interactive_blocks += 1
        elif block_type == "form":
            form_id = _learning_page_identifier(
                raw_block.get("form_id"), prefix="form", index=index, seen=form_ids
            )
            raw_fields = (
                raw_block.get("fields")
                if isinstance(raw_block.get("fields"), list)
                else []
            )
            fields = []
            field_ids: set[str] = set()
            for field_index, raw_field in enumerate(raw_fields[:30], start=1):
                if not isinstance(raw_field, dict) or total_fields >= 120:
                    continue
                field_type = str(raw_field.get("type") or "short_text").strip().lower()
                if field_type not in LEARNING_PAGE_FIELD_TYPES:
                    continue
                field_id = _learning_page_identifier(
                    raw_field.get("id"),
                    prefix="field",
                    index=field_index,
                    seen=field_ids,
                )
                label = _learning_page_text(raw_field.get("label"), 160)
                if not label:
                    continue
                field = {
                    "id": field_id,
                    "type": field_type,
                    "label": label,
                    "required": bool(raw_field.get("required", True)),
                    "placeholder": _learning_page_text(
                        raw_field.get("placeholder"), 200
                    ),
                }
                if field_type in {"single", "multiple", "select", "scale"}:
                    raw_options = (
                        raw_field.get("options")
                        if isinstance(raw_field.get("options"), list)
                        else []
                    )
                    options = []
                    for option in raw_options[:12]:
                        value = _learning_page_text(option, 120)
                        if value and value not in options:
                            options.append(value)
                    if field_type == "scale" and len(options) < 2:
                        options = ["1", "2", "3", "4", "5"]
                    if field_type != "scale" and len(options) < 2:
                        continue
                    field["options"] = options
                if field_type == "number":
                    try:
                        field["min"] = (
                            float(raw_field.get("min"))
                            if raw_field.get("min") not in {None, ""}
                            else None
                        )
                        field["max"] = (
                            float(raw_field.get("max"))
                            if raw_field.get("max") not in {None, ""}
                            else None
                        )
                    except (TypeError, ValueError):
                        field["min"] = None
                        field["max"] = None
                fields.append(field)
                total_fields += 1
            if not fields:
                continue
            block["form_id"] = form_id
            block["description"] = _learning_page_text(
                raw_block.get("description"), 600
            )
            block["submit_label"] = (
                _learning_page_text(raw_block.get("submit_label") or "提交", 32)
                or "提交"
            )
            block["fields"] = fields
        blocks.append(block)

    if not blocks:
        raise ServiceError(
            "AI 没有生成有效网页内容，请调整要求后重试。",
            errors={"schema": ["页面至少需要一个有效内容区块。"]},
            status=400,
        )
    return {
        "schema_version": 1,
        "title": title,
        "subtitle": subtitle,
        "accent": accent,
        "blocks": blocks,
    }


def _learning_page_generation_mode(direction: str, requested_mode: str) -> str:
    mode = str(requested_mode or "auto").strip().lower()
    if mode not in LEARNING_PAGE_GENERATION_MODES:
        raise ServiceError(
            "学习网页生成模式不正确。",
            errors={"generation_mode": ["只能选择智能、自由交互动画或受控演示。"]},
            status=400,
        )
    if mode != "auto":
        return mode
    animation_terms = (
        "动画",
        "交互",
        "模拟",
        "仿真",
        "canvas",
        "svg",
        "可视化",
        "演示过程",
        "动态展示",
    )
    normalized_direction = direction.lower()
    return (
        "interactive"
        if any(term in normalized_direction for term in animation_terms)
        else "structured"
    )


def _has_executable_interactive_block(schema: dict) -> bool:
    blocks = schema.get("blocks") if isinstance(schema, dict) else []
    if not isinstance(blocks, list):
        return False
    return any(
        isinstance(block, dict)
        and block.get("type") == "interactive"
        and bool(str(block.get("html") or "").strip())
        and len(str(block.get("javascript") or "").strip()) >= 20
        for block in blocks
    )


def generate_learning_web_page_schema(
    request,
    lesson: Lesson,
    direction: str,
    *,
    current_page: LearningWebPage | None = None,
    generation_mode: str = "auto",
) -> dict:
    direction = normalize_text(str(direction or ""))
    if len(direction) < 4 or len(direction) > 3000:
        raise ServiceError(
            "网页生成要求需为 4-3000 个字符。",
            errors={"direction": ["请填写清晰的学习网页要求。"]},
            status=400,
        )

    effective_mode = _learning_page_generation_mode(direction, generation_mode)
    system_prompt = (
        "你是 STRATA 数智教学系统的学习网页设计助手。"
        "你只能输出平台定义的 JSON 页面结构，禁止输出 Markdown、外链、iframe、图片 URL 或网络请求。"
        "只有 type=interactive 区块的 html、css、javascript 字段允许包含自包含网页代码；其他区块严禁包含 HTML、CSS、JavaScript。"
        "页面面向中学生课堂学习，内容要具体、简洁、可操作。只返回严格 JSON 对象。"
    )
    schema_example = {
        "title": "页面标题",
        "subtitle": "一句话学习目标",
        "accent": "blue",
        "blocks": [
            {"id": "intro", "type": "content", "title": "任务情境", "body": "学习内容"},
            {
                "id": "tips",
                "type": "callout",
                "tone": "info",
                "title": "提示",
                "body": "注意事项",
            },
            {
                "id": "steps",
                "type": "steps",
                "title": "操作步骤",
                "items": [{"title": "步骤一", "body": "说明"}],
            },
            {
                "id": "visual",
                "type": "visualization",
                "visualization_type": "process",
                "title": "过程可视化",
                "description": "按顺序演示关键变化",
                "duration_ms": 5000,
                "autoplay": True,
                "loop": False,
                "items": [
                    {
                        "label": "输入",
                        "detail": "接收原始数据",
                        "code": "A",
                        "tone": "blue",
                    },
                    {
                        "label": "转换",
                        "detail": "转换为编码",
                        "code": "01000001",
                        "tone": "cyan",
                    },
                    {"label": "输出", "detail": "完成存储或传输", "tone": "green"},
                ],
            },
            {
                "id": "custom_animation",
                "type": "interactive",
                "title": "自定义交互动画",
                "description": "需要自由布局或 Canvas/SVG 时使用",
                "height": 520,
                "html": '<div id="stage"><button id="play">播放</button><canvas id="canvas"></canvas></div>',
                "css": "#stage{padding:16px}canvas{display:block;width:100%;height:360px}",
                "javascript": "document.getElementById('play').addEventListener('click',()=>{/* 绘制动画 */});",
            },
            {
                "id": "form_block",
                "type": "form",
                "form_id": "learning_form",
                "title": "学习记录",
                "description": "完成后提交",
                "submit_label": "提交学习记录",
                "fields": [
                    {
                        "id": "choice",
                        "type": "single",
                        "label": "请选择",
                        "required": True,
                        "options": ["A", "B", "C"],
                    },
                    {
                        "id": "reflection",
                        "type": "long_text",
                        "label": "学习反思",
                        "required": True,
                        "placeholder": "写下你的思考",
                    },
                ],
            },
        ],
    }
    payload = {
        "task": "修改学习网页" if current_page else "创建学习网页",
        "course": lesson.course.title,
        "subject": lesson.course.subject.name if lesson.course.subject_id else "",
        "lesson": lesson.title,
        "teacher_requirement": direction,
        "generation_mode": effective_mode,
        "allowed_block_types": sorted(LEARNING_PAGE_BLOCK_TYPES),
        "allowed_field_types": sorted(LEARNING_PAGE_FIELD_TYPES),
        "rules": [
            "可生成多个 form 区块，每个表单必须有唯一 form_id。",
            "表单字段 id 在所属表单内唯一；选择类字段必须提供 2-12 个 options。",
            "scale 默认使用 1-5 五级量表。",
            "content/callout 使用纯文本，不写 HTML 标签。",
            "需要表格时使用 table 的 headers 和 rows，需要代码时使用 code 区块。",
            "需要动态演示时必须使用 visualization 区块；visualization_type 只能是 process、timeline、bars、binary。",
            "visualization 的 items 使用 label、detail、code、value、tone；至少 2 项，最多 16 项。bars 必须提供 value，binary 建议提供 code。",
            "visualization 动画由平台固定渲染器执行，不输出 HTML、CSS、JavaScript。duration_ms 为 1500-15000，可设置 autoplay 和 loop。",
            "固定 visualization 无法表达的自由动画或交互模拟可使用 interactive 区块，字段为 html、css、javascript、height。",
            "interactive 必须完全自包含，可使用原生 DOM、CSS 动画、Canvas、内联 SVG 和 JavaScript；禁止外链、fetch、WebSocket、import、iframe、第三方库和资源 URL。",
            "interactive 的事件必须在 javascript 中使用 addEventListener 绑定，不能在 html 中使用 onclick 等内联事件属性。",
            "interactive 只用于动画或交互模拟；需要收集学生答案时必须另外生成平台 form 区块。",
            "教师要求把现有静态步骤改成动画时，应替换同主题 steps/cards 区块，不能保留静态副本后再追加重复动画。",
            "除 interactive 的 html/css/javascript 字段外，不输出任何链接、脚本、样式代码或未经平台定义的字段。",
        ],
        "schema_example": schema_example,
    }
    if effective_mode == "interactive":
        payload["mode_requirement"] = (
            "必须生成至少一个 type=interactive 的自由交互动画区块。该区块必须同时提供非空 html、css、javascript；"
            "javascript 必须真正驱动画面变化，使用 requestAnimationFrame、Web Animations API、定时器或 Canvas/SVG 重绘，"
            "并提供可点击的开始或重新播放控件。不能只返回 visualization、steps、cards 或静态图文来冒充动画。"
        )
    else:
        payload["mode_requirement"] = (
            "使用平台受控区块；动态演示使用 visualization，不生成 interactive 自定义代码。"
        )
    if current_page is not None:
        payload["current_page"] = current_page.schema
        payload["revision_rule"] = (
            "保留教师未要求修改的内容、表单 ID 和字段 ID，避免已有统计失去对应关系；若教师要求把某内容改成动画，替换同主题静态区块，不追加重复副本。"
        )
    raw_schema = _shared_services._call_teacher_chat_json(
        request,
        system_prompt=system_prompt,
        user_prompt=json.dumps(payload, ensure_ascii=False),
        max_tokens=12000,
    )
    cleaned_schema = clean_learning_web_page_schema(
        raw_schema, fallback_title=current_page.title if current_page else lesson.title
    )
    if effective_mode != "interactive" or _has_executable_interactive_block(
        cleaned_schema
    ):
        return cleaned_schema

    repair_payload = {
        **payload,
        "task": "纠正未生成成功的自由交互动画网页",
        "invalid_result": raw_schema,
        "repair_requirement": (
            "上一次结果没有可执行的 interactive 区块。请重新返回完整页面 JSON，并确保至少一个 interactive 区块包含 html、css 和不少于 20 字符的 javascript。"
            "脚本必须通过 addEventListener 绑定控件并真实播放动画；不要仅增加 visualization 区块。"
        ),
    }
    repaired_raw_schema = _shared_services._call_teacher_chat_json(
        request,
        system_prompt=system_prompt,
        user_prompt=json.dumps(repair_payload, ensure_ascii=False),
        max_tokens=12000,
    )
    repaired_schema = clean_learning_web_page_schema(
        repaired_raw_schema,
        fallback_title=current_page.title if current_page else lesson.title,
    )
    if not _has_executable_interactive_block(repaired_schema):
        raise ServiceError(
            "AI 未生成可执行动画，请补充动画对象、变化过程和交互方式后重试。",
            errors={
                "animation": ["自由动画必须包含可执行的 HTML、CSS 和 JavaScript。"]
            },
            status=400,
        )
    return repaired_schema


def _teacher_subject(
    request, raw_subject, errors: dict, *, required: bool = False
) -> Subject | None:
    if raw_subject in {None, ""}:
        if required:
            errors["subject"] = ["请选择学科。"]
        return None
    try:
        subject = Subject.objects.get(
            pk=int(raw_subject), school=request.user.school, is_active=True
        )
    except (Subject.DoesNotExist, TypeError, ValueError):
        errors["subject"] = ["请选择本校启用学科。"]
        return None
    return subject


def _status_to_active(data, *, default=False) -> bool:
    status = str(data.get("status", "")).strip()
    if status:
        return status == "published"
    return _clean_bool(data.get("is_active", default))


@transaction.atomic
def save_teacher_course(request, data, *, course: Course | None = None) -> Course:
    errors: dict[str, list[str]] = {}
    title = str(data.get("title", "")).strip()
    introduction = str(data.get("introduction", "")).strip()
    teaching_model = (
        str(data.get("teaching_model", Course.TeachingModel.PROJECT)).strip()
        or Course.TeachingModel.PROJECT
    )
    subject = _teacher_subject(request, data.get("subject"), errors)
    status = str(data.get("status", "")).strip()

    if not _fullmatch(COURSE_TITLE_PATTERN, title):
        errors["title"] = ["课程名称需为 2-128 位，可包含中文、字母、数字和常用标点。"]
    if len(introduction) > 5000:
        errors["introduction"] = ["课程简介不能超过 5000 个字符。"]
    if teaching_model not in {item.value for item in Course.TeachingModel}:
        errors["teaching_model"] = ["教学模式不正确。"]
    if status and status not in {"draft", "published"}:
        errors["status"] = ["课程状态只能为草稿或已发布。"]

    if errors:
        raise ServiceError("课程信息校验失败。", errors=errors, status=400)

    is_create = course is None
    if course is None:
        course = Course(teacher=request.user)
    course.subject = subject
    course.title = title
    course.introduction = introduction
    course.teaching_model = teaching_model
    course.is_active = _status_to_active(data, default=course.is_active)
    course.save()

    if "class_groups" in data or "target_classes" in data:
        set_teacher_course_classes(request, course, data)

    _shared_services.write_audit(
        request,
        "course.create" if is_create else "course.update",
        school=request.user.school,
        target_type="course",
        target_id=course.id,
        detail={
            "title": course.title,
            "status": "published" if course.is_active else "draft",
        },
    )
    return course


@transaction.atomic
def save_teacher_course_cover(request, course: Course, uploaded_file) -> Course:
    _validate_course_cover(uploaded_file)
    if course.cover:
        course.cover.delete(save=False)
    course.cover = uploaded_file
    course.save(update_fields=["cover", "updated_at"])
    _shared_services.write_audit(
        request,
        "course.cover.update",
        school=request.user.school,
        target_type="course",
        target_id=course.id,
        detail={"title": course.title, "filename": getattr(uploaded_file, "name", "")},
    )
    return course


@transaction.atomic
def delete_teacher_course_cover(request, course: Course) -> Course:
    if course.cover:
        course.cover.delete(save=False)
        course.cover = ""
        course.save(update_fields=["cover", "updated_at"])
    _shared_services.write_audit(
        request,
        "course.cover.delete",
        school=request.user.school,
        target_type="course",
        target_id=course.id,
        detail={"title": course.title},
    )
    return course


@transaction.atomic
def set_teacher_course_classes(request, course: Course, data) -> Course:
    errors: dict[str, list[str]] = {}
    raw_class_ids = data.get("class_groups", data.get("target_classes"))
    classes = _teacher_class_groups(
        request, raw_class_ids, errors, field="class_groups", allow_empty=True
    )
    if errors:
        raise ServiceError("课程班级范围校验失败。", errors=errors, status=400)

    class_ids = {class_group.id for class_group in classes}
    CourseClass.objects.filter(course=course).exclude(
        class_group_id__in=class_ids
    ).delete()
    for class_group in classes:
        CourseClass.objects.get_or_create(
            course=course,
            class_group=class_group,
            defaults={"created_by": request.user},
        )

    _shared_services.write_audit(
        request,
        "course.classes.update",
        school=request.user.school,
        target_type="course",
        target_id=course.id,
        detail={"title": course.title, "class_ids": sorted(class_ids)},
    )
    return course


def publish_teacher_course(request, course: Course) -> Course:
    if not course.subject_id:
        raise ServiceError(
            "课程发布前需要选择学科。",
            errors={"subject": ["课程发布前需要选择学科。"]},
            status=400,
        )
    if not course.course_classes.exists():
        raise ServiceError(
            "课程发布前至少需要绑定 1 个任教班级。",
            errors={"class_groups": ["请选择课程可见班级。"]},
            status=400,
        )
    if not course.lessons.exists():
        raise ServiceError("课程发布前至少需要创建 1 个课时。", status=400)
    course.is_active = True
    course.save(update_fields=["is_active", "updated_at"])
    _shared_services.write_audit(
        request,
        "course.publish",
        school=request.user.school,
        target_type="course",
        target_id=course.id,
        detail={"title": course.title},
    )
    return course


def archive_teacher_course(request, course: Course) -> Course:
    course.is_active = False
    course.save(update_fields=["is_active", "updated_at"])
    _shared_services.write_audit(
        request,
        "course.archive",
        school=request.user.school,
        target_type="course",
        target_id=course.id,
        detail={"title": course.title},
    )
    return course


def delete_teacher_course(request, course: Course) -> None:
    if course.is_active:
        raise ServiceError("已发布课程不能直接删除，请先停用。", status=400)
    blockers = []
    if LearningEvent.objects.filter(course=course).exists():
        blockers.append("学习行为")
    if course.classroom_sessions.exists():
        blockers.append("课堂记录")
    if course.lessons.filter(classroom_sessions__isnull=False).exists():
        blockers.append("课时课堂")
    if blockers:
        raise ServiceError(
            f"该课程已有{', '.join(blockers)}关联，不能物理删除；请保持停用状态。",
            status=400,
        )
    detail = {"title": course.title}
    target_id = course.id
    course.delete()
    _shared_services.write_audit(
        request,
        "course.delete",
        school=request.user.school,
        target_type="course",
        target_id=target_id,
        detail=detail,
    )


def save_teacher_lesson(
    request, course: Course, data, *, lesson: Lesson | None = None
) -> Lesson:
    errors: dict[str, list[str]] = {}
    title = str(data.get("title", "")).strip()
    content = str(data.get("content", "")).strip()
    sort_order = _clean_optional_int(
        data.get("sort_order"), "sort_order", errors, min_value=0, max_value=9999
    )
    status = str(data.get("status", "")).strip()

    if not _fullmatch(COURSE_TITLE_PATTERN, title):
        errors["title"] = ["课时名称需为 2-128 位，可包含中文、字母、数字和常用标点。"]
    if len(content) > 5000:
        errors["content"] = ["课时内容不能超过 5000 个字符。"]
    if status and status not in {"draft", "published"}:
        errors["status"] = ["课时状态只能为草稿或已发布。"]

    if errors:
        raise ServiceError("课时信息校验失败。", errors=errors, status=400)

    is_create = lesson is None
    if lesson is None:
        max_order = course.lessons.aggregate(value=Max("sort_order")).get("value") or 0
        lesson = Lesson(
            course=course,
            sort_order=sort_order if sort_order is not None else max_order + 10,
        )
    else:
        lesson.sort_order = sort_order if sort_order is not None else lesson.sort_order
    lesson.title = title
    lesson.content = content
    lesson.is_active = _status_to_active(data, default=lesson.is_active)
    lesson.save()
    _shared_services.write_audit(
        request,
        "lesson.create" if is_create else "lesson.update",
        school=request.user.school,
        target_type="lesson",
        target_id=lesson.id,
        detail={
            "course": course.id,
            "title": lesson.title,
            "status": "published" if lesson.is_active else "draft",
        },
    )
    return lesson


def publish_teacher_lesson(request, lesson: Lesson) -> Lesson:
    lesson.is_active = True
    lesson.save(update_fields=["is_active", "updated_at"])
    _shared_services.write_audit(
        request,
        "lesson.publish",
        school=request.user.school,
        target_type="lesson",
        target_id=lesson.id,
        detail={"course": lesson.course_id, "title": lesson.title},
    )
    return lesson


def archive_teacher_lesson(request, lesson: Lesson) -> Lesson:
    lesson.is_active = False
    lesson.save(update_fields=["is_active", "updated_at"])
    _shared_services.write_audit(
        request,
        "lesson.archive",
        school=request.user.school,
        target_type="lesson",
        target_id=lesson.id,
        detail={"course": lesson.course_id, "title": lesson.title},
    )
    return lesson


def delete_teacher_lesson(request, lesson: Lesson) -> None:
    if lesson.is_active:
        raise ServiceError("已发布课时不能直接删除，请先停用。", status=400)
    blockers = []
    if LearningEvent.objects.filter(lesson=lesson).exists():
        blockers.append("学习行为")
    if lesson.classroom_sessions.exists():
        blockers.append("课堂记录")
    if blockers:
        raise ServiceError(
            f"该课时已有{', '.join(blockers)}关联，不能物理删除；请保持停用状态。",
            status=400,
        )
    detail = {"course": lesson.course_id, "title": lesson.title}
    target_id = lesson.id
    lesson.delete()
    _shared_services.write_audit(
        request,
        "lesson.delete",
        school=request.user.school,
        target_type="lesson",
        target_id=target_id,
        detail=detail,
    )


def _clean_string_items(
    data, field: str, errors: dict, *, max_items: int = 20, max_length: int = 128
) -> list[str]:
    raw_items = data.get(field, [])
    if raw_items is None or raw_items == "":
        return []
    if not isinstance(raw_items, list):
        errors[field] = ["数据格式不正确。"]
        return []

    items: list[str] = []
    for raw_item in raw_items:
        text = str(raw_item).strip()
        if not text:
            continue
        if len(text) > max_length:
            errors[field] = [f"单项内容不能超过 {max_length} 个字符。"]
            continue
        if text not in items:
            items.append(text)

    if len(items) > max_items:
        errors[field] = [f"最多填写 {max_items} 项。"]
        return items[:max_items]
    return items


def _resource_binding(resource: Resource) -> dict:
    attachment_url = ""
    attachment_name = ""
    file_ext = ""
    if resource.attachment:
        attachment_url = protected_file_url("resource-attachment", resource.id)
        attachment_name = resource.attachment.name.rsplit("/", 1)[-1]
        file_ext = clean_resource_ext(attachment_name, attachment_url)
    return {
        "id": resource.id,
        "title": resource.title,
        "content": resource.content,
        "attachment_url": attachment_url,
        "attachment_name": attachment_name,
        "file_ext": file_ext,
        "external_url": resource.external_url,
        "resource_type": resource.resource_type,
        "kind": "resource",
    }


def _clean_resource_items(
    request,
    data,
    field: str,
    errors: dict,
    *,
    lesson: Lesson | None = None,
    max_items: int = 30,
) -> list[dict]:
    raw_items = data.get(field, [])
    if raw_items is None or raw_items == "":
        return []
    if not isinstance(raw_items, list):
        errors[field] = ["资源数据格式不正确。"]
        return []

    items: list[dict] = []
    seen = set()
    for raw_item in raw_items:
        if isinstance(raw_item, dict):
            kind = str(raw_item.get("kind") or "resource").strip()
            if kind == "learning_page":
                try:
                    page_id = int(raw_item.get("learning_page_id") or 0)
                except (TypeError, ValueError):
                    page_id = 0
                page = LearningWebPage.objects.filter(
                    pk=page_id,
                    teacher=request.user,
                    school=request.user.school,
                    is_active=True,
                ).first()
                if page is None or (lesson is not None and page.lesson_id != lesson.id):
                    errors[field] = ["AI 学习网页不存在、无权绑定或不属于当前课时。"]
                    continue
                key = f"learning_page:{page.id}"
                if key not in seen:
                    seen.add(key)
                    items.append(
                        {
                            "id": f"learning-page-{page.id}",
                            "learning_page_id": page.id,
                            "title": page.title,
                            "attachment_url": "",
                            "attachment_name": "",
                            "file_ext": "",
                            "kind": "learning_page",
                            "revision_no": page.revision_no,
                        }
                    )
                continue
            raw_id = raw_item.get("id") or raw_item.get("resource_id")
            if raw_id:
                try:
                    resource_id = int(raw_id)
                except (TypeError, ValueError):
                    errors[field] = ["资源编号不正确。"]
                    continue
                resource = (
                    Resource.objects.filter(pk=resource_id)
                    .filter(
                        Q(owner=request.user, owner__school=request.user.school)
                        | Q(
                            owner__school=request.user.school,
                            visibility=Resource.Visibility.SCHOOL,
                            publish_status=Resource.PublishStatus.PUBLISHED,
                        )
                        | Q(
                            visibility=Resource.Visibility.EXTERNAL,
                            publish_status=Resource.PublishStatus.APPROVED,
                        )
                    )
                    .first()
                )
                if resource is None:
                    errors[field] = ["资源不存在或无权绑定。"]
                    continue
                key = f"resource:{resource.id}"
                if key not in seen:
                    seen.add(key)
                    items.append(_resource_binding(resource))
                continue
            text = str(raw_item.get("title") or raw_item.get("name") or "").strip()
        else:
            text = str(raw_item).strip()

        if not text:
            continue
        if len(text) > 128:
            errors[field] = ["资源名称不能超过 128 个字符。"]
            continue
        key = f"legacy:{text}"
        if key not in seen:
            seen.add(key)
            file_ext = clean_resource_ext(text)
            items.append(
                {
                    "id": "",
                    "title": text,
                    "attachment_url": "",
                    "attachment_name": text,
                    "file_ext": file_ext,
                    "kind": "legacy",
                }
            )

    if len(items) > max_items:
        errors[field] = [f"最多绑定 {max_items} 个资源。"]
        return items[:max_items]
    return items


def _clean_lesson_file_config(raw_config) -> dict:
    config = raw_config if isinstance(raw_config, dict) else {}
    raw_extensions = config.get("allowed_extensions")
    if not isinstance(raw_extensions, list):
        raw_extensions = LESSON_FILE_DEFAULT_EXTENSIONS
    extensions: list[str] = []
    for raw_extension in raw_extensions:
        ext = clean_resource_ext(str(raw_extension))
        if ext in LESSON_FILE_ALLOWED_EXTENSIONS and ext not in extensions:
            extensions.append(ext)
    if not extensions:
        extensions = list(LESSON_FILE_DEFAULT_EXTENSIONS)
    try:
        max_size_mb = int(config.get("max_size_mb", 100) or 100)
    except (TypeError, ValueError):
        max_size_mb = 100
    return {
        "allowed_extensions": extensions[:24],
        "max_size_mb": min(max(max_size_mb, 1), 512),
    }


def _clean_lesson_question_items(
    data, field: str, errors: dict, *, max_items: int = 30
) -> list[dict]:
    raw_items = data.get(field, [])
    if raw_items is None or raw_items == "":
        return []
    if not isinstance(raw_items, list):
        errors[field] = ["题目数据格式不正确。"]
        return []

    items: list[dict] = []
    seen_ids = set()
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            errors[field] = ["题目数据格式不正确。"]
            continue

        question_type = str(
            raw_item.get("question_type") or raw_item.get("type") or "single"
        ).strip()
        stem = str(raw_item.get("stem") or raw_item.get("title") or "").strip()
        analysis = str(raw_item.get("analysis") or "").strip()
        raw_options = raw_item.get("options", [])
        raw_answer = raw_item.get("answer", [])
        raw_id = str(raw_item.get("id") or "").strip()
        target_layer = (
            str(raw_item.get("target_layer") or LessonStep.TargetLayer.ALL).strip()
            or LessonStep.TargetLayer.ALL
        )
        use_layer_scores = _clean_bool(raw_item.get("use_layer_scores", False))
        raw_layer_scores = (
            raw_item.get("layer_scores")
            if isinstance(raw_item.get("layer_scores"), dict)
            else {}
        )
        question_id = (
            raw_id
            if re.fullmatch(r"[A-Za-z0-9_-]{3,40}", raw_id)
            else f"q_{uuid4().hex[:12]}"
        )
        while question_id in seen_ids:
            question_id = f"q_{uuid4().hex[:12]}"
        seen_ids.add(question_id)

        if question_type not in LESSON_QUESTION_TYPES:
            errors[field] = ["题型不正确。"]
            continue
        if target_layer not in {item.value for item in LessonStep.TargetLayer}:
            errors[field] = ["题目适用层级不正确。"]
            continue
        if not 2 <= len(stem) <= 1000:
            errors[field] = ["题干需为 2-1000 个字符。"]
            continue
        if len(analysis) > 1000:
            errors[field] = ["解析不能超过 1000 个字符。"]
            continue

        options: list[str] = []
        if question_type == "judge":
            options = ["正确", "错误"]
        elif question_type in {"single", "multiple"}:
            if isinstance(raw_options, list):
                for option in raw_options:
                    text = normalize_text(str(option))
                    if text and text not in options:
                        options.append(text[:200])
            if len(options) < 2:
                errors[field] = ["单选题和多选题至少需要 2 个选项。"]
                continue
            options = options[:8]

        if isinstance(raw_answer, list):
            answer = [
                normalize_text(str(value))
                for value in raw_answer
                if normalize_text(str(value))
            ]
        elif raw_answer is None or raw_answer == "":
            answer = []
        else:
            answer = [normalize_text(str(raw_answer))]
        if question_type == "single" and len(answer) > 1:
            answer = answer[:1]
        if question_type == "judge" and answer and answer[0] not in {"正确", "错误"}:
            answer = []
        if question_type in {"single", "multiple"} and answer:
            answer = [value for value in answer if value in options]
        if question_type == "file":
            answer = []

        try:
            score = float(
                raw_item.get("score", _lesson_question_base_score(question_type)) or 0
            )
        except (TypeError, ValueError):
            errors[field] = ["题目分值必须是数字。"]
            score = 0
        if score < 0 or score > 100:
            errors[field] = ["题目分值需在 0-100 之间。"]
            continue

        layer_scores: dict[str, float] = {}
        layer_score_error = False
        for layer_code in ("A", "B", "C"):
            raw_layer_score = raw_layer_scores.get(layer_code, score)
            if raw_layer_score is None or raw_layer_score == "":
                raw_layer_score = score
            try:
                layer_score = float(raw_layer_score)
            except (TypeError, ValueError):
                errors[field] = [f"{layer_code} 层分值必须是数字。"]
                layer_score_error = True
                layer_score = score
            if layer_score < 0 or layer_score > 100:
                errors[field] = [f"{layer_code} 层分值需在 0-100 之间。"]
                layer_score_error = True
                continue
            layer_scores[layer_code] = layer_score
        if layer_score_error:
            continue

        sort_order = _clean_optional_int(
            raw_item.get("sort_order", (index + 1) * 10),
            field,
            errors,
            min_value=0,
            max_value=9999,
        )
        items.append(
            {
                "id": question_id,
                "question_type": question_type,
                "stem": stem,
                "options": options,
                "answer": answer,
                "score": score,
                "target_layer": target_layer,
                "use_layer_scores": use_layer_scores,
                "layer_scores": layer_scores,
                "analysis": analysis,
                "is_required": _clean_bool(raw_item.get("is_required", True)),
                "sort_order": (
                    sort_order if sort_order is not None else (index + 1) * 10
                ),
                "file_config": (
                    _clean_lesson_file_config(raw_item.get("file_config"))
                    if question_type == "file"
                    else {}
                ),
            }
        )

    if len(items) > max_items:
        errors[field] = [f"最多配置 {max_items} 道题。"]
        items = items[:max_items]
    return sorted(items, key=lambda item: (item["sort_order"], item["id"]))


def save_lesson_step(
    request, lesson: Lesson, data, *, step: LessonStep | None = None
) -> LessonStep:
    errors: dict[str, list[str]] = {}
    title = str(data.get("title", "")).strip()
    step_type = (
        str(data.get("step_type", LessonStep.StepType.RESOURCE)).strip()
        or LessonStep.StepType.RESOURCE
    )
    student_instruction = str(data.get("student_instruction", "")).strip()
    teacher_note = str(data.get("teacher_note", "")).strip()
    ai_prompt = str(data.get("ai_prompt", "")).strip()
    sort_order = _clean_optional_int(
        data.get("sort_order"), "sort_order", errors, min_value=0, max_value=9999
    )
    estimated_minutes = _clean_optional_int(
        data.get("estimated_minutes"),
        "estimated_minutes",
        errors,
        min_value=1,
        max_value=240,
    )
    target_layer = (
        str(data.get("target_layer", LessonStep.TargetLayer.ALL)).strip()
        or LessonStep.TargetLayer.ALL
    )
    status = (
        str(data.get("status", LessonStep.Status.DRAFT)).strip()
        or LessonStep.Status.DRAFT
    )
    resource_items = _clean_resource_items(
        request, data, "resource_items", errors, lesson=lesson, max_items=30
    )
    activity_items = _clean_string_items(
        data, "activity_items", errors, max_items=30, max_length=128
    )
    question_items = _clean_lesson_question_items(
        data, "question_items", errors, max_items=30
    )

    if not _fullmatch(COURSE_TITLE_PATTERN, title):
        errors["title"] = ["环节标题需为 2-128 位，可包含中文、字母、数字和常用标点。"]
    if step_type not in {item.value for item in LessonStep.StepType}:
        errors["step_type"] = ["环节类型不正确。"]
    if len(student_instruction) > 5000:
        errors["student_instruction"] = ["学生可见说明不能超过 5000 个字符。"]
    if len(teacher_note) > 5000:
        errors["teacher_note"] = ["教师备课备注不能超过 5000 个字符。"]
    if len(ai_prompt) > 3000:
        errors["ai_prompt"] = ["AI 生成目标不能超过 3000 个字符。"]
    if target_layer not in {item.value for item in LessonStep.TargetLayer}:
        errors["target_layer"] = ["目标层级不正确。"]
    if status not in {item.value for item in LessonStep.Status}:
        errors["status"] = ["环节状态不正确。"]

    if errors:
        raise ServiceError("课时环节校验失败。", errors=errors, status=400)

    is_create = step is None
    if step is None:
        max_order = lesson.steps.aggregate(value=Max("sort_order")).get("value") or 0
        step = LessonStep(
            lesson=lesson,
            created_by=request.user,
            sort_order=sort_order if sort_order is not None else max_order + 10,
        )
    else:
        step.sort_order = sort_order if sort_order is not None else step.sort_order

    step.title = title
    step.step_type = step_type
    step.student_instruction = student_instruction
    step.teacher_note = teacher_note
    step.estimated_minutes = (
        estimated_minutes if estimated_minutes is not None else step.estimated_minutes
    )
    step.target_layer = target_layer
    step.status = status
    step.is_required = _clean_bool(data.get("is_required", step.is_required))
    step.collect_student_log = _clean_bool(
        data.get("collect_student_log", step.collect_student_log)
    )
    step.collect_class_log = _clean_bool(
        data.get("collect_class_log", step.collect_class_log)
    )
    step.resource_items = resource_items
    step.activity_items = activity_items
    step.question_items = question_items
    step.ai_prompt = ai_prompt
    step.save()

    _shared_services.write_audit(
        request,
        "lesson_step.create" if is_create else "lesson_step.update",
        school=request.user.school,
        target_type="lesson_step",
        target_id=step.id,
        detail={
            "lesson": lesson.id,
            "title": step.title,
            "type": step.step_type,
            "status": step.status,
        },
    )
    return step


def delete_lesson_step(request, step: LessonStep) -> None:
    detail = {
        "lesson": step.lesson_id,
        "title": step.title,
        "type": step.step_type,
        "status": step.status,
    }
    target_id = step.id
    step.delete()
    _shared_services.write_audit(
        request,
        "lesson_step.delete",
        school=request.user.school,
        target_type="lesson_step",
        target_id=target_id,
        detail=detail,
    )


@transaction.atomic
def reorder_lesson_steps(request, lesson: Lesson, data) -> list[LessonStep]:
    raw_ids = data.get("ids") if hasattr(data, "get") else None
    if not isinstance(raw_ids, list):
        raise ServiceError(
            "请提交环节排序数据。", errors={"ids": ["请提交环节排序数据。"]}, status=400
        )

    ids: list[int] = []
    for raw_id in raw_ids:
        try:
            step_id = int(raw_id)
        except (TypeError, ValueError):
            raise ServiceError(
                "环节排序编号不正确。",
                errors={"ids": ["环节排序编号不正确。"]},
                status=400,
            )
        if step_id not in ids:
            ids.append(step_id)

    steps = list(
        LessonStep.objects.filter(lesson=lesson, id__in=ids).order_by(
            "sort_order", "id"
        )
    )
    if len(steps) != len(ids):
        raise ServiceError(
            "部分环节不存在或不属于当前课时。",
            errors={"ids": ["部分环节不存在或不属于当前课时。"]},
            status=404,
        )

    by_id = {step.id: step for step in steps}
    for index, step_id in enumerate(ids, start=1):
        step = by_id[step_id]
        step.sort_order = index * 10
        step.save(update_fields=["sort_order", "updated_at"])

    _shared_services.write_audit(
        request,
        "lesson_step.reorder",
        school=request.user.school,
        target_type="lesson",
        target_id=lesson.id,
        detail={"step_ids": ids},
    )
    return list(LessonStep.objects.filter(lesson=lesson).order_by("sort_order", "id"))
