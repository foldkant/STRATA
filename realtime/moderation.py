from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class ModerationResult:
    content: str
    fingerprint: str
    flagged: bool
    severity: str
    categories: list[str]
    matched_rules: list[str]


RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("severe", "威胁伤害", ("打死你", "弄死你", "杀了你", "砍死你", "废了你", "你去死", "去死吧")),
    ("moderate", "侮辱攻击", ("傻逼", "傻b", "蠢货", "废物", "脑残", "垃圾人", "有病吧", "滚蛋")),
    ("moderate", "粗俗辱骂", ("妈的", "他妈的", "操你", "草你", "nmsl")),
    ("mild", "不文明表达", ("闭嘴", "滚开", "真垃圾", "真恶心", "不要脸")),
)

REGEX_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("severe", "威胁伤害", re.compile(r"(?:我要|敢不敢|放学后)?.{0,6}(?:打|揍|杀|砍|弄死).{0,4}你")),
    ("moderate", "侮辱攻击", re.compile(r"你(?:就是|真是|怎么这么).{0,5}(?:蠢|笨|废物|垃圾|恶心)")),
)

SEVERITY_RANK = {"none": 0, "mild": 1, "moderate": 2, "severe": 3}
DEFAULT_DEDUCTION = {"mild": 1.0, "moderate": 3.0, "severe": 5.0}


def clean_chat_content(value: object) -> str:
    content = unicodedata.normalize("NFKC", str(value or ""))
    content = "".join(char for char in content if char in "\n\t" or unicodedata.category(char) not in {"Cc", "Cf"})
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    content = re.sub(r"[ \t]+", " ", content)
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    return content


def normalized_for_matching(content: str) -> str:
    normalized = unicodedata.normalize("NFKC", content).lower()
    normalized = normalized.translate(str.maketrans({"０": "0", "１": "1", "３": "3", "５": "5", "＠": "@"}))
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", normalized)


def moderate_content(value: object) -> ModerationResult:
    content = clean_chat_content(value)
    normalized = normalized_for_matching(content)
    fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    severity = "none"
    categories: list[str] = []
    matches: list[str] = []

    for rule_severity, category, terms in RULES:
        for term in terms:
            if normalized_for_matching(term) not in normalized:
                continue
            if category not in categories:
                categories.append(category)
            label = f"{category}：{term}"
            if label not in matches:
                matches.append(label)
            if SEVERITY_RANK[rule_severity] > SEVERITY_RANK[severity]:
                severity = rule_severity

    for rule_severity, category, pattern in REGEX_RULES:
        if not pattern.search(normalized):
            continue
        if category not in categories:
            categories.append(category)
        label = f"{category}：攻击性表达"
        if label not in matches:
            matches.append(label)
        if SEVERITY_RANK[rule_severity] > SEVERITY_RANK[severity]:
            severity = rule_severity

    standalone_rules = {
        "垃圾": ("mild", "不文明表达"),
        "滚": ("mild", "不文明表达"),
    }
    if normalized in standalone_rules:
        rule_severity, category = standalone_rules[normalized]
        if category not in categories:
            categories.append(category)
        label = f"{category}：{normalized}"
        if label not in matches:
            matches.append(label)
        if SEVERITY_RANK[rule_severity] > SEVERITY_RANK[severity]:
            severity = rule_severity

    return ModerationResult(
        content=content,
        fingerprint=fingerprint,
        flagged=bool(matches),
        severity=severity,
        categories=categories,
        matched_rules=matches,
    )
