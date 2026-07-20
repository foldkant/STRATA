from django.core.management.base import BaseCommand, CommandError

from learning_analytics.services.model_packages import verify_model_package


class Command(BaseCommand):
    help = "Verify an offline model package using a pinned Ed25519 public key."

    def add_arguments(self, parser):
        parser.add_argument("package")
        parser.add_argument("--public-key", required=True)

    def handle(self, *args, **options):
        try:
            with open(options["public_key"], "rb") as handle:
                public_key = handle.read()
            manifest = verify_model_package(
                options["package"], trusted_public_key=public_key
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("Model package signature is valid."))
        self.stdout.write(f"Package ID: {manifest['package_id']}")
        self.stdout.write(f"School: {manifest['school']['code']}")
        self.stdout.write(f"Release version: {manifest['release_version']}")
