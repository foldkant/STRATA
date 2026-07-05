from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or update the local super administrator account."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="superadmin")
        parser.add_argument("--password", default="SuperAdmin12345")
        parser.add_argument("--display-name", default="超级管理员")

    def handle(self, *args, **options):
        User = get_user_model()
        user, created = User.objects.get_or_create(username=options["username"])
        user.role = "super_admin"
        user.display_name = options["display_name"]
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.is_first_login = False
        user.set_password(options["password"])
        user.save()
        verb = "created" if created else "updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} super administrator: {user.username}"))
