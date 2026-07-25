"""Fail CI when known oversized source files grow again.

These caps are a temporary guardrail, not a target architecture. Each cap should
only move downward as a domain component or service is extracted.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Current baselines after the 2026-07-25 curriculum, classroom and student-side
# integration pass. The user has deferred further source splitting, so these
# values freeze the current state and must not be raised for routine changes.
LINE_BUDGETS = {
    "api/views.py": 3570,
    "api/classroom_views.py": 3277,
    "api/student_views.py": 2887,
    "api/services.py": 2553,
    "frontend/src/views/teacher/ClassroomConsoleView.vue": 2571,
    "frontend/src/views/teacher/LessonDesignerView.vue": 2111,
    "frontend/src/views/super-admin/CurriculumStandardsView.vue": 2303,
    "frontend/src/styles/learning-and-classroom.css": 6528,
    "frontend/src/styles/core-and-analysis.css": 5374,
    "frontend/src/styles/assessments.css": 3574,
    "frontend/src/styles/interaction-foundations.css": 602,
}


def line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as source:
        return sum(1 for _ in source)


def main() -> int:
    failures: list[str] = []
    for relative_path, maximum in LINE_BUDGETS.items():
        path = ROOT / relative_path
        if not path.exists():
            failures.append(f"{relative_path}: 文件不存在，需更新体积约束清单")
            continue
        actual = line_count(path)
        if actual > maximum:
            failures.append(
                f"{relative_path}: {actual} 行，超过当前上限 {maximum} 行；"
                "请先提取领域组件或服务，或在评审中说明新的约束"
            )
        else:
            print(f"OK {relative_path}: {actual}/{maximum}")

    if failures:
        print("\n源文件体积约束未通过：")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\n源文件体积约束通过。后续拆分时应同步下调对应上限。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
