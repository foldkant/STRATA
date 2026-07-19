from __future__ import annotations

import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from learning_analytics.services.synthetic_data import (
    SyntheticDataConfig,
    SyntheticDataError,
    estimate_synthetic_dataset,
    generate_synthetic_dataset,
)
from learning_analytics.models import SyntheticDatasetRun


class Command(BaseCommand):
    help = "Generate an isolated, deterministic longitudinal synthetic dataset."

    def add_arguments(self, parser):
        parser.add_argument("--school-code", default="SIM-RESEARCH")
        parser.add_argument("--school-name", default="STRATA 合成研究学校")
        parser.add_argument(
            "--mode",
            choices=[item.value for item in SyntheticDatasetRun.Mode],
            default=SyntheticDatasetRun.Mode.ISOLATED_SCHOOL,
        )
        parser.add_argument(
            "--teacher-username",
            default="",
            help="Required for school_overlay; generated courses belong to this teacher.",
        )
        parser.add_argument("--seed", type=int, default=20260719)
        parser.add_argument("--classes", type=int, default=2)
        parser.add_argument("--students-per-class", type=int, default=12)
        parser.add_argument("--weeks", type=int, default=4)
        parser.add_argument(
            "--end-date",
            default="",
            help="Last generated local date in YYYY-MM-DD; defaults to yesterday.",
        )
        parser.add_argument("--skip-quality", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        raw_end_date = str(options["end_date"] or "").strip()
        end_date = (
            parse_date(raw_end_date)
            if raw_end_date
            else timezone.localdate() - timedelta(days=1)
        )
        if end_date is None:
            raise CommandError("--end-date must use YYYY-MM-DD.")
        config = SyntheticDataConfig(
            school_code=str(options["school_code"]).strip().upper(),
            school_name=str(options["school_name"]).strip(),
            seed=int(options["seed"]),
            class_count=int(options["classes"]),
            students_per_class=int(options["students_per_class"]),
            weeks=int(options["weeks"]),
            end_date=end_date,
            mode=str(options["mode"]),
            teacher_username=str(options["teacher_username"] or "").strip(),
        )
        try:
            result = (
                estimate_synthetic_dataset(config)
                if options["dry_run"]
                else generate_synthetic_dataset(
                    config,
                    run_quality=not bool(options["skip_quality"]),
                )
            )
        except SyntheticDataError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        )
