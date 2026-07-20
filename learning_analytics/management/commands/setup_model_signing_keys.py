from django.core.management.base import BaseCommand, CommandError

from learning_analytics.services.model_packages import generate_model_signing_keys


class Command(BaseCommand):
    help = "Generate the local Ed25519 key pair used to sign offline model packages."

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Replace the current key pair. Existing packages will require the old public key.",
        )

    def handle(self, *args, **options):
        try:
            result = generate_model_signing_keys(overwrite=options["overwrite"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        action = "created" if result["created"] else "already exists"
        self.stdout.write(self.style.SUCCESS(f"Signing key pair {action}."))
        self.stdout.write(f"Public key: {result['public_path']}")
        self.stdout.write(f"Key ID: {result['key_id']}")
