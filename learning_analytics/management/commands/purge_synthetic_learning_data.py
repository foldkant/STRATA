from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from learning_analytics.models import SyntheticDatasetRun
from learning_analytics.services.synthetic_cleanup import (
    SyntheticCleanupError,
    purge_synthetic_dataset,
    synthetic_cleanup_preview,
)


class Command(BaseCommand):
    help = "Purge one synthetic dataset after exact dataset-key confirmation."

    def add_arguments(self, parser):
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--confirm-key", default="")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        run = SyntheticDatasetRun.objects.filter(run_id=options["run_id"]).first()
        if run is None:
            raise CommandError("Synthetic dataset run was not found.")
        if options["dry_run"]:
            result = synthetic_cleanup_preview(run)
        else:
            try:
                result = purge_synthetic_dataset(
                    run=run,
                    confirmation_key=str(options["confirm_key"] or "").strip(),
                )
            except SyntheticCleanupError as exc:
                raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        )
