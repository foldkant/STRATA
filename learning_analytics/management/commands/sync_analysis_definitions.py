from django.core.management.base import BaseCommand

from learning_analytics.services.feature_registry import (
    sync_feature_and_outcome_definitions,
)


class Command(BaseCommand):
    help = "同步版本化学习特征和未来结果定义。"

    def handle(self, *args, **options):
        result = sync_feature_and_outcome_definitions()
        feature_set = result["feature_set"]
        self.stdout.write(
            self.style.SUCCESS(
                f"已同步 {result['feature_count']} 个特征定义、"
                f"{result['outcome_count']} 个未来结果定义；"
                f"当前特征集 {feature_set.set_key}@{feature_set.version}。"
            )
        )
