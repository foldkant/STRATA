from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model

from ops.forms import (
    PERSON_NAME_PATTERN,
    PHONE_PATTERN,
    TEACHING_PASSWORD_PATTERN,
    USERNAME_PATTERN,
    StyledFormMixin,
    XlsxImportForm,
    _matches,
)

TEACHER_USERNAME_HELP_TEXT = "5-32 位，以字母开头，可包含字母、数字和下划线；例如 teacher1，下划线可用但不是必需"


class TeacherCreateForm(StyledFormMixin, forms.Form):
    username = forms.CharField(
        label="登录账号",
        max_length=32,
        widget=forms.TextInput(
            attrs={
                "placeholder": "例如：teacher1",
                "pattern": USERNAME_PATTERN,
                "title": TEACHER_USERNAME_HELP_TEXT,
            }
        ),
    )
    display_name = forms.CharField(
        label="姓名",
        max_length=24,
        widget=forms.TextInput(
            attrs={
                "placeholder": "例如：张老师",
                "pattern": PERSON_NAME_PATTERN,
                "title": "2-24 位中文或字母",
            }
        ),
    )
    phone = forms.CharField(
        label="联系电话",
        max_length=24,
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "可为空",
                "pattern": PHONE_PATTERN,
                "title": "请输入手机号或带区号的固定电话",
            }
        ),
    )
    password = forms.CharField(
        label="初始密码",
        min_length=6,
        max_length=32,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "6-32 位，允许课堂简易密码",
                "pattern": TEACHING_PASSWORD_PATTERN,
                "title": "6-32 位，可使用字母、数字和 @#$%^&*_.!+-",
                "autocomplete": "new-password",
            }
        ),
    )
    is_active = forms.BooleanField(label="启用账号", required=False, initial=True)

    def __init__(self, *args, school=None, **kwargs):
        self.school = school
        super().__init__(*args, **kwargs)
        self._apply_widget_attrs()

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if not _matches(USERNAME_PATTERN, username):
            raise forms.ValidationError("账号需为 5-32 位，以字母开头，可包含字母、数字和下划线；例如 teacher1，下划线可用但不是必需。")
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("该登录账号已存在。")
        return username

    def clean_display_name(self):
        display_name = self.cleaned_data["display_name"].strip()
        if not _matches(PERSON_NAME_PATTERN, display_name):
            raise forms.ValidationError("姓名需为 2-24 位中文或字母。")
        return display_name

    def clean_phone(self):
        phone = self.cleaned_data.get("phone", "").strip()
        if phone and not _matches(PHONE_PATTERN, phone):
            raise forms.ValidationError("联系电话格式不正确。")
        return phone

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not _matches(TEACHING_PASSWORD_PATTERN, password):
            raise forms.ValidationError("教师密码需为 6-32 位，可使用字母、数字和常用符号。")
        return password


class TeacherUpdateForm(TeacherCreateForm):
    password = None

    def __init__(self, *args, teacher=None, school=None, **kwargs):
        self.teacher = teacher
        initial = kwargs.setdefault("initial", {})
        if teacher is not None and (not args or args[0] is None):
            initial.update(
                {
                    "username": teacher.username,
                    "display_name": teacher.display_name,
                    "phone": teacher.phone,
                    "is_active": teacher.is_active,
                }
            )
        super().__init__(*args, school=school, **kwargs)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if not _matches(USERNAME_PATTERN, username):
            raise forms.ValidationError("账号需为 5-32 位，以字母开头，可包含字母、数字和下划线；例如 teacher1，下划线可用但不是必需。")
        User = get_user_model()
        queryset = User.objects.filter(username=username)
        if self.teacher is not None:
            queryset = queryset.exclude(pk=self.teacher.pk)
        if queryset.exists():
            raise forms.ValidationError("该登录账号已存在。")
        return username


class TeacherPasswordResetForm(StyledFormMixin, forms.Form):
    password = forms.CharField(
        label="新密码",
        min_length=6,
        max_length=32,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "6-32 位，允许课堂简易密码",
                "pattern": TEACHING_PASSWORD_PATTERN,
                "title": "6-32 位，可使用字母、数字和 @#$%^&*_.!+-",
                "autocomplete": "new-password",
            }
        ),
    )
    confirm_password = forms.CharField(
        label="确认密码",
        min_length=6,
        max_length=32,
        widget=forms.PasswordInput(attrs={"placeholder": "再次输入新密码", "autocomplete": "new-password"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_attrs()

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not _matches(TEACHING_PASSWORD_PATTERN, password):
            raise forms.ValidationError("教师密码需为 6-32 位，可使用字母、数字和常用符号。")
        return password

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "两次输入的密码不一致。")
        return cleaned_data


class TeacherImportForm(XlsxImportForm):
    pass
