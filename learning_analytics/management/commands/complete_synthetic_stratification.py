from __future__ import annotations

import json

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from learning_analytics.models import ClassCalibrationRun
from learning_analytics.services.synthetic_stratification import (
    complete_synthetic_stratification,
)


class Command(BaseCommand):
    help = "Publish and adopt one synthetic stratification candidate for UI testing."

    def add_arguments(self, parser):
        parser.add_argument("--calibration-id", type=int, required=True)
        parser.add_argument("--actor-username", required=True)
        parser.add_argument("--confirm-key", required=True)

    def handle(self, *args, **options):
        calibration = (
            ClassCalibrationRun.objects.select_related(
                "school", "dataset__synthetic_run", "subject"
            )
            .filter(pk=options["calibration_id"])
            .first()
        )
        if calibration is None:
            raise CommandError("候选模型不存在。")
        actor = User.objects.filter(username=options["actor_username"]).first()
        if actor is None:
            raise CommandError("操作账户不存在。")
        try:
            result = complete_synthetic_stratification(
                calibration_run=calibration,
                actor=actor,
                confirmation_key=str(options["confirm_key"]).strip(),
            )
        except ValidationError as exc:
            message = "; ".join(exc.messages) if exc.messages else str(exc)
            raise CommandError(message) from exc
        self.stdout.write(
            json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        )
