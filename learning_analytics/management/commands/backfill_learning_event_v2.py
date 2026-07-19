from __future__ import annotations

import json
from datetime import datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from learning.models import LearningEvent
from learning_analytics.services.legacy_backfill import backfill_legacy_event
from school.models import School


class Command(BaseCommand):
    help = "Deterministically backfill V1 LearningEvent rows into V2 or legacy.unmapped."

    def add_arguments(self, parser):
        parser.add_argument(
            "--school",
            default="",
            help="School id or code. Omit to process every school.",
        )
        parser.add_argument(
            "--before",
            default="",
            help="Only process rows before this ISO date/datetime.",
        )
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument(
            "--resume",
            type=int,
            default=0,
            help="Resume after this legacy LearningEvent id.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def _school(self, value: str):
        if not value:
            return None
        query = School.objects.filter(pk=int(value)) if value.isdigit() else School.objects.filter(code=value)
        school = query.first()
        if school is None:
            raise CommandError("School was not found.")
        return school

    def _before(self, value: str):
        if not value:
            return None
        parsed = parse_datetime(value)
        if parsed is None:
            parsed_date = parse_date(value)
            if parsed_date is None:
                raise CommandError("--before must be an ISO date or datetime.")
            parsed = datetime.combine(parsed_date, time.max)
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    def handle(self, *args, **options):
        batch_size = int(options["batch_size"])
        resume = int(options["resume"])
        if not 1 <= batch_size <= 5000:
            raise CommandError("--batch-size must be between 1 and 5000.")
        if resume < 0:
            raise CommandError("--resume cannot be negative.")
        school = self._school(str(options["school"] or "").strip())
        before = self._before(str(options["before"] or "").strip())
        dry_run = bool(options["dry_run"])

        query = LearningEvent.objects.select_related(
            "actor__school",
            "class_group",
            "course__subject",
            "lesson",
            "analytics_event_v2",
        ).filter(pk__gt=resume)
        if school is not None:
            query = query.filter(actor__school=school)
        if before is not None:
            query = query.filter(occurred_at__lt=before)
        query = query.order_by("pk")

        counts = {
            "eligible": query.count(),
            "mapped": 0,
            "unmapped": 0,
            "rejected": 0,
            "duplicate": 0,
        }
        reason_counts: dict[str, int] = {}
        rejected_examples = []
        last_id = resume
        for event in query.iterator(chunk_size=batch_size):
            last_id = event.id
            try:
                result = backfill_legacy_event(event, dry_run=dry_run)
            except Exception as exc:  # Command must continue and report isolated failures.
                counts["rejected"] += 1
                if len(rejected_examples) < 20:
                    rejected_examples.append(
                        {
                            "legacy_event_id": event.id,
                            "error": f"{type(exc).__name__}: {exc}"[:500],
                        }
                    )
                continue
            counts[result.status] += 1
            if result.reason_code:
                reason_counts[result.reason_code] = (
                    reason_counts.get(result.reason_code, 0) + 1
                )

        report = {
            **counts,
            "dry_run": dry_run,
            "school": school.code if school else "all",
            "before": before.isoformat() if before else None,
            "resume_after": resume,
            "last_processed_id": last_id,
            "reason_counts": dict(sorted(reason_counts.items())),
            "rejected_examples": rejected_examples,
        }
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        if counts["rejected"]:
            raise CommandError(
                f"Backfill finished with {counts['rejected']} rejected rows."
            )
