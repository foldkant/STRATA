from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("平台信息", {"fields": ("role", "school", "display_name", "phone", "is_first_login", "legacy_id")}),
    )
    list_display = ("username", "display_name", "role", "school", "is_active", "is_first_login")
    list_filter = ("role", "school", "is_active", "is_first_login")
