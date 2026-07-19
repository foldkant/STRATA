from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


STUDENT_HIDDEN_FIELD_NAMES = frozenset(
    {
        "current_layer",
        "current_layer_label",
        "current_group_no",
        "target_layer",
        "target_layer_label",
        "target_layers",
        "layer_scores",
        "use_layer_scores",
        "is_layered",
        "layer_hint",
        "grouping_strategy",
        "grouping_strategy_label",
        "content_band",
        "delivered_band",
        "candidate_band",
        "confidence",
        "risk_probability",
        "model_reason",
        "model_explanation",
    }
)

_DISPLAY_FIELD_SUFFIXES = (
    "name",
    "title",
    "label",
    "filename",
    "file_name",
    "attachment_name",
)
_ABILITY_LABEL_PATTERN = re.compile(
    r"(?:^|[\s_\-（(])(?:A|B|C)\s*层|低水平组|高水平组|同层组|异层组",
    re.IGNORECASE,
)


def _path(parent: str, child: object) -> str:
    return f"{parent}.{child}" if parent else str(child)


def find_student_privacy_violations(value, *, path: str = "") -> list[str]:
    violations: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            key = str(raw_key)
            nested_path = _path(path, key)
            if key in STUDENT_HIDDEN_FIELD_NAMES:
                violations.append(nested_path)
                continue
            if (
                isinstance(nested, str)
                and key.lower().endswith(_DISPLAY_FIELD_SUFFIXES)
                and _ABILITY_LABEL_PATTERN.search(nested)
            ):
                violations.append(nested_path)
                continue
            violations.extend(
                find_student_privacy_violations(nested, path=nested_path)
            )
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, nested in enumerate(value):
            violations.extend(
                find_student_privacy_violations(
                    nested,
                    path=f"{path}[{index}]" if path else f"[{index}]",
                )
            )
    return violations


def is_student_safe_payload(value) -> bool:
    return not find_student_privacy_violations(value)
