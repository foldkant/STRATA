from __future__ import annotations

import re

from django import forms
from django.contrib.auth import get_user_model

from school.models import School

from .models import ImportBatch


SCHOOL_NAME_PATTERN = r"^[\u4e00-\u9fa5A-Za-z0-9（）()·\-\s]{2,80}$"
SCHOOL_CODE_PATTERN = r"^[A-Z0-9][A-Z0-9_-]{1,31}$"
PERSON_NAME_PATTERN = r"^[\u4e00-\u9fa5A-Za-z·\s]{2,24}$"
USERNAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{4,31}$"
USERNAME_HELP_TEXT = "5-32 位，以字母开头，可包含字母、数字和下划线；例如 schooladmin1，下划线可用但不是必需"
PHONE_PATTERN = r"^(\+?86[- ]?)?(1[3-9]\d{9}|0\d{2,3}[- ]?\d{7,8})$"
PASSWORD_PATTERN = r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d@#$%^&*_.!+\-]{8,32}$"
TEACHING_PASSWORD_PATTERN = r"^[A-Za-z0-9@#$%^&*_.!+\-]{6,32}$"


def _matches(pattern: str, value: str) -> bool:
    return bool(re.fullmatch(pattern, value))


class StyledFormMixin:
    def _apply_widget_attrs(self) -> None:
        for field in self.fields.values():
            widget = field.widget
            css_class = "ops-input"
            if isinstance(widget, forms.Select):
                css_class = "ops-select"
            elif isinstance(widget, forms.Textarea):
                css_class = "ops-textarea"
            elif isinstance(widget, forms.FileInput):
                css_class = "ops-file"
            widget.attrs["class"] = css_class


class SchoolForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = School
        fields = ["name", "code", "contact_name", "contact_phone", "address", "status", "note"]
        labels = {
            "name": "学校名称",
            "code": "学校编号",
            "contact_name": "联系人",
            "contact_phone": "联系电话",
            "address": "学校地址",
            "status": "状态",
            "note": "备注",
        }
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "例如：小榄中学",
                    "pattern": SCHOOL_NAME_PATTERN,
                    "maxlength": "80",
                    "title": "2-80 位，可包含中文、字母、数字、空格、括号和短横线",
                }
            ),
            "code": forms.TextInput(
                attrs={
                    "placeholder": "例如：XLZX",
                    "pattern": SCHOOL_CODE_PATTERN,
                    "maxlength": "32",
                    "title": "2-32 位，大写字母、数字、下划线或短横线",
                }
            ),
            "contact_name": forms.TextInput(
                attrs={
                    "placeholder": "例如：张老师",
                    "pattern": PERSON_NAME_PATTERN,
                    "maxlength": "24",
                    "title": "2-24 位，可包含中文、字母、空格和间隔点",
                }
            ),
            "contact_phone": forms.TextInput(
                attrs={
                    "placeholder": "例如：13800138000 或 0760-88888888",
                    "pattern": PHONE_PATTERN,
                    "maxlength": "24",
                    "title": "请输入手机号或带区号的固定电话",
                }
            ),
            "address": forms.TextInput(attrs={"placeholder": "学校所在地", "maxlength": "255"}),
            "note": forms.Textarea(attrs={"placeholder": "内部维护备注，可为空", "rows": "4"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_attrs()

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not _matches(SCHOOL_NAME_PATTERN, name):
            raise forms.ValidationError("学校名称需为 2-80 位，可包含中文、字母、数字、空格、括号和短横线。")
        return name

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        if not _matches(SCHOOL_CODE_PATTERN, code):
            raise forms.ValidationError("学校编号需为 2-32 位大写字母、数字、下划线或短横线。")
        return code

    def clean_contact_name(self):
        contact_name = self.cleaned_data.get("contact_name", "").strip()
        if contact_name and not _matches(PERSON_NAME_PATTERN, contact_name):
            raise forms.ValidationError("联系人需为 2-24 位中文或字母。")
        return contact_name

    def clean_contact_phone(self):
        phone = self.cleaned_data.get("contact_phone", "").strip()
        if phone and not _matches(PHONE_PATTERN, phone):
            raise forms.ValidationError("联系电话格式不正确，请输入手机号或带区号的固定电话。")
        return phone


class SchoolAdminCreateForm(StyledFormMixin, forms.Form):
    school = forms.ModelChoiceField(label="所属学校", queryset=School.objects.order_by("name"))
    username = forms.CharField(
        label="登录账号",
        max_length=32,
        widget=forms.TextInput(
            attrs={
                "placeholder": "例如：schooladmin1",
                "pattern": USERNAME_PATTERN,
                "title": USERNAME_HELP_TEXT,
            }
        ),
    )
    display_name = forms.CharField(
        label="姓名",
        max_length=24,
        widget=forms.TextInput(
            attrs={
                "placeholder": "例如：学校管理员",
                "pattern": PERSON_NAME_PATTERN,
                "title": "2-24 位中文或字母",
            }
        ),
    )
    password = forms.CharField(
        label="初始密码",
        min_length=8,
        max_length=32,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "8-32 位，至少包含字母和数字",
                "pattern": PASSWORD_PATTERN,
                "title": "8-32 位，至少包含字母和数字，可使用 @#$%^&*_.!+-",
                "autocomplete": "new-password",
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
    is_active = forms.BooleanField(label="启用账号", required=False, initial=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_attrs()

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if not _matches(USERNAME_PATTERN, username):
            raise forms.ValidationError("账号需为 5-32 位，以字母开头，可包含字母、数字和下划线；例如 schooladmin1，下划线可用但不是必需。")
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("该登录账号已存在。")
        return username

    def clean_display_name(self):
        display_name = self.cleaned_data["display_name"].strip()
        if not _matches(PERSON_NAME_PATTERN, display_name):
            raise forms.ValidationError("姓名需为 2-24 位中文或字母。")
        return display_name

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not _matches(PASSWORD_PATTERN, password):
            raise forms.ValidationError("密码需为 8-32 位，并至少包含字母和数字。")
        return password

    def clean_phone(self):
        phone = self.cleaned_data.get("phone", "").strip()
        if phone and not _matches(PHONE_PATTERN, phone):
            raise forms.ValidationError("联系电话格式不正确。")
        return phone


class SchoolAdminUpdateForm(StyledFormMixin, forms.Form):
    school = forms.ModelChoiceField(label="所属学校", queryset=School.objects.order_by("name"))
    username = forms.CharField(
        label="登录账号",
        max_length=32,
        widget=forms.TextInput(
            attrs={
                "pattern": USERNAME_PATTERN,
                "title": USERNAME_HELP_TEXT,
            }
        ),
    )
    display_name = forms.CharField(
        label="姓名",
        max_length=24,
        widget=forms.TextInput(attrs={"pattern": PERSON_NAME_PATTERN, "title": "2-24 位中文或字母"}),
    )
    phone = forms.CharField(
        label="联系电话",
        max_length=24,
        required=False,
        widget=forms.TextInput(attrs={"pattern": PHONE_PATTERN, "title": "请输入手机号或带区号的固定电话"}),
    )
    password = forms.CharField(
        label="重置密码",
        required=False,
        min_length=8,
        max_length=32,
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "留空表示不修改",
                "pattern": PASSWORD_PATTERN,
                "title": "8-32 位，至少包含字母和数字",
                "autocomplete": "new-password",
            }
        ),
    )
    is_active = forms.BooleanField(label="启用账号", required=False)

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        initial = kwargs.setdefault("initial", {})
        if user is not None and (not args or args[0] is None):
            initial.update(
                {
                    "school": user.school,
                    "username": user.username,
                    "display_name": user.display_name,
                    "phone": user.phone,
                    "is_active": user.is_active,
                }
            )
        super().__init__(*args, **kwargs)
        self._apply_widget_attrs()

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if not _matches(USERNAME_PATTERN, username):
            raise forms.ValidationError("账号需为 5-32 位，以字母开头，可包含字母、数字和下划线；例如 schooladmin1，下划线可用但不是必需。")
        User = get_user_model()
        queryset = User.objects.filter(username=username)
        if self.user is not None:
            queryset = queryset.exclude(pk=self.user.pk)
        if queryset.exists():
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
        password = self.cleaned_data.get("password", "")
        if password and not _matches(PASSWORD_PATTERN, password):
            raise forms.ValidationError("密码需为 8-32 位，并至少包含字母和数字。")
        return password


class XlsxImportForm(StyledFormMixin, forms.Form):
    file = forms.FileField(
        label="Excel 文件",
        widget=forms.FileInput(
            attrs={
                "accept": ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "title": "请选择按模板填写的 xlsx 文件",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_attrs()

    def clean_file(self):
        file = self.cleaned_data["file"]
        if not file.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("只能上传 xlsx 文件，请先下载模板填写。")
        max_size = 20 * 1024 * 1024
        if file.size > max_size:
            raise forms.ValidationError("Excel 文件不能超过 20MB。")
        return file


class ImportBatchUploadForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ImportBatch
        fields = ["package_file"]
        labels = {"package_file": "数据采集包"}
        widgets = {
            "package_file": forms.FileInput(
                attrs={
                    "accept": ".zip,application/zip,application/x-zip-compressed",
                    "title": "请选择学校导出的 zip 数据采集包",
                }
            )
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_widget_attrs()

    def clean_package_file(self):
        package_file = self.cleaned_data["package_file"]
        if not package_file.name.lower().endswith(".zip"):
            raise forms.ValidationError("只能上传 zip 数据采集包。")
        max_size = 1024 * 1024 * 1024
        if package_file.size > max_size:
            raise forms.ValidationError("数据采集包不能超过 1GB。")
        return package_file
