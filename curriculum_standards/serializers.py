from __future__ import annotations

from rest_framework import serializers

from .models import (
    CurriculumDocumentType,
    CurriculumProcessingMode,
    CurriculumProcessingPriority,
    CurriculumRetrievalBackend,
    CurriculumRetrievalSourceKind,
    CurriculumStandard,
    CurriculumStandardNode,
    CurriculumStandardVersion,
    CurriculumVersionStatus,
    SchoolStage,
)


class StrictSerializerMixin:
    def to_internal_value(self, data):
        if not hasattr(data, "keys"):
            raise serializers.ValidationError("必须提交对象。")
        unknown = sorted(set(data.keys()) - set(self.fields))
        if unknown:
            raise serializers.ValidationError(
                {"unknown_fields": [f"未登记字段：{field}" for field in unknown]}
            )
        return super().to_internal_value(data)


class CurriculumProcessingJobCreateSerializer(
    StrictSerializerMixin,
    serializers.Serializer,
):
    mode = serializers.ChoiceField(
        choices=CurriculumProcessingMode.choices,
        default=CurriculumProcessingMode.AUTO,
        required=False,
    )
    priority = serializers.ChoiceField(
        choices=CurriculumProcessingPriority.choices,
        default=CurriculumProcessingPriority.LOW,
        required=False,
    )


class CurriculumStandardWriteSerializer(
    StrictSerializerMixin,
    serializers.ModelSerializer,
):
    class Meta:
        model = CurriculumStandard
        fields = (
            "title",
            "document_type",
            "school_stage",
            "subject_code",
            "subject_name",
            "is_active",
        )
        extra_kwargs = {
            "title": {"required": True, "allow_blank": False},
            "is_active": {"required": False},
            "subject_code": {"required": False, "allow_blank": True},
            "subject_name": {"required": False, "allow_blank": True},
        }

    def validate(self, attrs):
        instance = self.instance
        document_type = attrs.get(
            "document_type",
            instance.document_type if instance else None,
        )
        subject_code = str(
            attrs.get("subject_code", instance.subject_code if instance else "") or ""
        ).strip()
        subject_name = str(
            attrs.get("subject_name", instance.subject_name if instance else "") or ""
        ).strip()
        if document_type == CurriculumDocumentType.SUBJECT_STANDARD:
            if not subject_code:
                raise serializers.ValidationError(
                    {"subject_code": "学科课程标准必须填写学科代码。"}
                )
            if not subject_name:
                raise serializers.ValidationError(
                    {"subject_name": "学科课程标准必须填写学科名称。"}
                )
        if instance and instance.versions.exists():
            immutable = ("document_type", "school_stage", "subject_code")
            changed = [
                field
                for field in immutable
                if field in attrs and attrs[field] != getattr(instance, field)
            ]
            if changed:
                raise serializers.ValidationError(
                    "课程标准已有版本，不能更改文档类型、学段或学科代码。"
                )
        attrs["subject_code"] = subject_code
        attrs["subject_name"] = subject_name
        attrs["title"] = str(attrs.get("title", instance.title if instance else "")).strip()
        return attrs

    def create(self, validated_data):
        actor = self.context["request"].user
        return CurriculumStandard.objects.create(
            created_by=actor,
            updated_by=actor,
            **validated_data,
        )

    def update(self, instance, validated_data):
        instance.updated_by = self.context["request"].user
        for field_name, value in validated_data.items():
            setattr(instance, field_name, value)
        instance.save()
        return instance


class CurriculumVersionCreateSerializer(StrictSerializerMixin, serializers.Serializer):
    version_label = serializers.CharField(max_length=80)
    publication_year = serializers.IntegerField(min_value=1900, max_value=2200)
    effective_year = serializers.IntegerField(
        min_value=1900,
        max_value=2200,
        required=False,
        allow_null=True,
    )
    issued_by = serializers.CharField(
        max_length=160,
        required=False,
        default="中华人民共和国教育部",
    )
    official_title = serializers.CharField(max_length=240, required=False, allow_blank=True)
    source_url = serializers.URLField(max_length=1000, required=False, allow_blank=True)
    source_note = serializers.CharField(required=False, allow_blank=True)
    pdf_file = serializers.FileField()
    structured_text = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    structured_file = serializers.FileField(required=False, allow_null=True, write_only=True)
    replaces_version = serializers.PrimaryKeyRelatedField(
        queryset=CurriculumStandardVersion.objects.none(),
        required=False,
        allow_null=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        standard = self.context.get("standard")
        if standard:
            self.fields["replaces_version"].queryset = standard.versions.exclude(
                status=CurriculumVersionStatus.DRAFT
            )

    def validate(self, attrs):
        structured_file = attrs.pop("structured_file", None)
        if structured_file:
            if getattr(structured_file, "size", 0) > 20 * 1024 * 1024:
                raise serializers.ValidationError(
                    {"structured_file": "结构化文本文件不能超过 20 MB。"}
                )
            try:
                decoded = structured_file.read().decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise serializers.ValidationError(
                    {"structured_file": "结构化文本文件必须使用 UTF-8 编码。"}
                ) from exc
            if attrs.get("structured_text") and attrs["structured_text"].strip():
                raise serializers.ValidationError(
                    {"structured_file": "结构化文本和文本文件只能提交一种。"}
                )
            attrs["structured_text"] = decoded
        attrs.setdefault("structured_text", "")
        attrs.setdefault("effective_year", None)
        attrs.setdefault("source_url", "")
        attrs.setdefault("official_title", "")
        attrs.setdefault("source_note", "")
        attrs.setdefault("replaces_version", None)
        return attrs


class CurriculumVersionDraftUpdateSerializer(
    StrictSerializerMixin,
    serializers.Serializer,
):
    version_label = serializers.CharField(max_length=80, required=False)
    publication_year = serializers.IntegerField(
        min_value=1900,
        max_value=2200,
        required=False,
    )
    effective_year = serializers.IntegerField(
        min_value=1900,
        max_value=2200,
        required=False,
        allow_null=True,
    )
    issued_by = serializers.CharField(max_length=160, required=False)
    official_title = serializers.CharField(max_length=240, required=False, allow_blank=True)
    source_url = serializers.URLField(max_length=1000, required=False, allow_blank=True)
    source_note = serializers.CharField(required=False, allow_blank=True)
    structured_text = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    structured_file = serializers.FileField(required=False, allow_null=True, write_only=True)
    replaces_version = serializers.PrimaryKeyRelatedField(
        queryset=CurriculumStandardVersion.objects.none(),
        required=False,
        allow_null=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        version = self.context.get("version")
        if version:
            self.fields["replaces_version"].queryset = version.source.versions.exclude(
                pk=version.pk
            ).exclude(status=CurriculumVersionStatus.DRAFT)

    def validate(self, attrs):
        structured_file = attrs.pop("structured_file", None)
        if structured_file:
            if getattr(structured_file, "size", 0) > 20 * 1024 * 1024:
                raise serializers.ValidationError(
                    {"structured_file": "结构化文本文件不能超过 20 MB。"}
                )
            try:
                decoded = structured_file.read().decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise serializers.ValidationError(
                    {"structured_file": "结构化文本文件必须使用 UTF-8 编码。"}
                ) from exc
            if attrs.get("structured_text") and attrs["structured_text"].strip():
                raise serializers.ValidationError(
                    {"structured_file": "结构化文本和文本文件只能提交一种。"}
                )
            attrs["structured_text"] = decoded
        return attrs


class CurriculumNodeWriteSerializer(
    StrictSerializerMixin,
    serializers.ModelSerializer,
):
    parent = serializers.PrimaryKeyRelatedField(
        queryset=CurriculumStandardNode.objects.none(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = CurriculumStandardNode
        fields = (
            "node_type",
            "code",
            "title",
            "content",
            "parent",
            "source_page_start",
            "source_page_end",
            "source_paragraph",
            "sort_order",
        )
        extra_kwargs = {
            "source_paragraph": {"required": False, "allow_blank": True},
            "sort_order": {"required": False},
            "parent": {"required": False},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        version = self.context.get("version")
        if version:
            queryset = version.nodes.all()
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)
            self.fields["parent"].queryset = queryset

    def validate(self, attrs):
        for field in ("code", "title", "content", "source_paragraph"):
            if field in attrs:
                attrs[field] = str(attrs[field] or "").strip()
        return attrs

    def create(self, validated_data):
        return CurriculumStandardNode.objects.create(
            version=self.context["version"],
            **validated_data,
        )

    def update(self, instance, validated_data):
        for field_name, value in validated_data.items():
            setattr(instance, field_name, value)
        instance.save()
        return instance


class CurriculumRetrievalIndexBuildSerializer(
    StrictSerializerMixin,
    serializers.Serializer,
):
    max_chars = serializers.IntegerField(
        required=False,
        min_value=256,
        max_value=8000,
    )
    overlap_chars = serializers.IntegerField(required=False, min_value=0)

    def validate(self, attrs):
        max_chars = attrs.get("max_chars", 1200)
        overlap_chars = attrs.get("overlap_chars", 200)
        if overlap_chars >= max_chars:
            raise serializers.ValidationError(
                {"overlap_chars": "重叠字符数必须小于最大字符数。"}
            )
        return attrs


class CurriculumRetrievalSearchSerializer(
    StrictSerializerMixin,
    serializers.Serializer,
):
    q = serializers.CharField(max_length=240, trim_whitespace=True)
    version_id = serializers.IntegerField(required=False, min_value=1)
    school_stage = serializers.ChoiceField(
        choices=SchoolStage.choices,
        required=False,
        allow_blank=True,
    )
    subject_code = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
    )
    source_kind = serializers.ChoiceField(
        choices=CurriculumRetrievalSourceKind.choices,
        required=False,
        allow_blank=True,
    )
    include_history = serializers.BooleanField(required=False, default=False)
    include_unpublished = serializers.BooleanField(required=False, default=False)
    backend = serializers.ChoiceField(
        choices=CurriculumRetrievalBackend.choices,
        required=False,
        default=CurriculumRetrievalBackend.KEYWORD,
    )
    limit = serializers.IntegerField(required=False, min_value=1, max_value=50, default=20)

    def validate_q(self, value):
        if len("".join(value.split())) < 2:
            raise serializers.ValidationError("请输入至少两个字符的检索词。")
        return value

    def validate(self, attrs):
        if attrs.get("include_unpublished") and not attrs.get("version_id"):
            raise serializers.ValidationError(
                {"version_id": "检索未发布内容时必须明确指定课程标准版本。"}
            )
        return attrs
