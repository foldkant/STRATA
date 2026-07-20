from datetime import date, timedelta

from django.test import SimpleTestCase

from learning_analytics.services.advanced_models import (
    ADVANCED_MODEL_KEYS,
    fit_advanced_model,
    predict_advanced_model,
)
from learning_analytics.services.model_comparison import ComparisonRow
from learning_analytics.services.class_calibration import friendly_decision_reason


class AdvancedModelSmokeTests(SimpleTestCase):
    feature_keys = ["completion_rate__7d", "active_minutes__30d"]

    def rows(self, count: int, *, offset: int = 0) -> list[ComparisonRow]:
        return [
            ComparisonRow(
                row_id=offset + index + 1,
                pseudonymous_key=f"{offset + index + 1:064x}",
                class_key=str(index % 4),
                decision_date=date(2026, 1, 1) + timedelta(days=index % 6),
                features={
                    "completion_rate__7d": (index % 10) / 10,
                    "active_minutes__30d": float(20 + index % 30),
                },
                outcome=float((index + index // 3) % 3),
            )
            for index in range(count)
        ]

    def test_structured_models_return_predictions_for_windowed_features(self):
        train = self.rows(48)
        test = self.rows(12, offset=100)

        for model_key in ADVANCED_MODEL_KEYS:
            with self.subTest(model_key=model_key):
                model = fit_advanced_model(
                    model_key,
                    train,
                    self.feature_keys,
                    "continuous",
                )
                predictions = predict_advanced_model(
                    model,
                    model_key,
                    test,
                    self.feature_keys,
                    "continuous",
                )

                self.assertEqual(len(predictions), len(test))
                self.assertTrue(
                    all(item.status == "predicted" for item in predictions)
                )
                self.assertTrue(all(item.value is not None for item in predictions))


class DecisionReasonFormattingTests(SimpleTestCase):
    def test_legacy_ratio_reason_is_presented_as_teacher_facing_percentage(self):
        self.assertEqual(
            friendly_decision_reason("resource_completion_rate（30d）：0.25"),
            "近 30 日资源完成率：25%",
        )

    def test_unknown_reason_is_preserved(self):
        self.assertEqual(
            friendly_decision_reason("依据当前学习记录形成建议。"),
            "依据当前学习记录形成建议。",
        )
