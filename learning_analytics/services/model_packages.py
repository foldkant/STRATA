from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import uuid
import zipfile
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from learning.models import StratificationDecision
from learning_analytics.feature_models import canonical_hash
from learning_analytics.model_models import (
    ClassCalibrationRun,
    ModelComparisonRun,
    ModelRelease,
    ModelReleaseAudit,
)
from school.models import School


PACKAGE_SCHEMA_VERSION = "1.0"
SYSTEM_RELEASE_NOTE_PREFIX = "系统切换模型版本："


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _key_paths() -> tuple[Path, Path]:
    return (
        Path(settings.MODEL_SIGNING_PRIVATE_KEY_PATH).resolve(),
        Path(settings.MODEL_SIGNING_PUBLIC_KEY_PATH).resolve(),
    )


def generate_model_signing_keys(*, overwrite: bool = False) -> dict:
    private_path, public_path = _key_paths()
    if not overwrite and (private_path.exists() or public_path.exists()):
        if private_path.exists() and public_path.exists():
            public_bytes = public_path.read_bytes()
            return {
                "private_path": str(private_path),
                "public_path": str(public_path),
                "key_id": _public_key_id(public_bytes),
                "created": False,
            }
        raise ValidationError("模型签名密钥不完整，请由学校部署管理员重新生成。")

    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    for path, content in ((private_path, private_bytes), (public_path, public_bytes)):
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            handle.write(content)
            temporary = Path(handle.name)
        os.replace(temporary, path)
    try:
        os.chmod(private_path, 0o600)
    except OSError:
        pass
    return {
        "private_path": str(private_path),
        "public_path": str(public_path),
        "key_id": _public_key_id(public_bytes),
        "created": True,
    }


def _public_key_id(public_bytes: bytes) -> str:
    public_key = serialization.load_pem_public_key(public_bytes)
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValidationError("模型签名公钥不是 Ed25519 公钥。")
    der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return _sha256_bytes(der)


def _load_signing_keys() -> tuple[Ed25519PrivateKey, bytes, str]:
    private_path, public_path = _key_paths()
    if not private_path.exists() or not public_path.exists():
        if not settings.MODEL_SIGNING_AUTO_CREATE:
            raise ValidationError(
                "学校尚未配置模型签名密钥，请先运行 setup_model_signing_keys。"
            )
        generate_model_signing_keys()
    try:
        private_key = serialization.load_pem_private_key(
            private_path.read_bytes(), password=None
        )
        public_bytes = public_path.read_bytes()
    except (OSError, ValueError, TypeError) as exc:
        raise ValidationError("模型签名密钥无法读取。") from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValidationError("模型签名私钥不是 Ed25519 私钥。")
    public_key = serialization.load_pem_public_key(public_bytes)
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValidationError("模型签名公钥不是 Ed25519 公钥。")
    if private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ) != public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ):
        raise ValidationError("模型签名公钥与私钥不匹配。")
    return private_key, public_bytes, _public_key_id(public_bytes)


def _artifact_path(run: ClassCalibrationRun) -> Path:
    if not run.artifact_path:
        raise ValidationError("候选模型没有可发布的模型文件。")
    root = Path(settings.MODEL_ARTIFACT_ROOT).resolve()
    raw_path = Path(run.artifact_path)
    path = (raw_path if raw_path.is_absolute() else settings.BASE_DIR / raw_path).resolve()
    if not path.is_relative_to(root):
        raise ValidationError("候选模型文件不在学校模型目录中。")
    if not path.is_file():
        raise ValidationError("候选模型文件不存在。")
    if _sha256_file(path) != run.artifact_hash:
        raise ValidationError("候选模型文件校验失败，发布已停止。")
    return path


def _validate_candidate(run: ClassCalibrationRun) -> Path:
    if run.status != ClassCalibrationRun.Status.CANDIDATE:
        raise ValidationError("只能发布已通过基础检查的候选模型。")
    if run.comparison_run.status != ModelComparisonRun.Status.SHADOW_ONLY:
        raise ValidationError("模型比较未通过，候选模型不能发布。")
    if run.manifest.get("blockers") or run.comparison_run.manifest.get("blockers"):
        raise ValidationError("候选模型仍有阻塞问题，不能发布。")
    if not run.model_key:
        raise ValidationError("候选模型没有选择可用算法。")
    if not run.model_card.get("teacher_confirmation_required"):
        raise ValidationError("候选模型缺少教师确认约束，不能发布。")
    return _artifact_path(run)


def _package_manifest(
    *,
    run: ClassCalibrationRun,
    release_version: int,
    package_id: str,
    artifact_path: Path,
    key_id: str,
) -> dict:
    return {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "package_id": package_id,
        "created_at": timezone.now().isoformat(),
        "school": {"code": run.school.code, "name": run.school.name},
        "subject": {"code": run.subject.code, "name": run.subject.name},
        "release_version": release_version,
        "is_test_data": bool(run.dataset.synthetic_run_id),
        "calibration": {
            "run_id": str(run.run_id),
            "version": run.calibration_version,
            "manifest_hash": run.manifest_hash,
            "model_key": run.model_key,
        },
        "comparison": {
            "run_id": str(run.comparison_run.run_id),
            "version": run.comparison_run.comparison_version,
            "manifest_hash": run.comparison_run.manifest_hash,
        },
        "dataset": {
            "dataset_id": str(run.dataset.dataset_id),
            "dataset_key": run.dataset.dataset_key,
            "manifest_hash": run.dataset.manifest_hash,
        },
        "artifact": {
            "filename": artifact_path.name,
            "sha256": run.artifact_hash,
        },
        "signing": {"algorithm": "Ed25519", "key_id": key_id},
        "rules": {
            "teacher_confirmation_required": True,
            "student_layer_hidden": True,
            "automatic_layer_change": False,
        },
    }


def _build_package(
    *, run: ClassCalibrationRun, release_version: int
) -> tuple[Path, dict, str, str, str]:
    artifact_path = _validate_candidate(run)
    private_key, public_bytes, key_id = _load_signing_keys()
    package_id = str(uuid.uuid4())
    manifest = _package_manifest(
        run=run,
        release_version=release_version,
        package_id=package_id,
        artifact_path=artifact_path,
        key_id=key_id,
    )
    manifest_bytes = _canonical_json(manifest)
    signature = private_key.sign(manifest_bytes)
    package_root = Path(settings.MODEL_PACKAGE_ROOT).resolve()
    folder = package_root / f"school_{run.school_id}" / f"subject_{run.subject_id}"
    folder.mkdir(parents=True, exist_ok=True)
    final_path = folder / f"model-v{release_version}-{package_id}.zip"
    with tempfile.NamedTemporaryFile(
        suffix=".zip", dir=folder, prefix=".building-", delete=False
    ) as handle:
        temporary_path = Path(handle.name)
    try:
        with zipfile.ZipFile(
            temporary_path, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as bundle:
            bundle.writestr("manifest.json", manifest_bytes)
            bundle.writestr("signature.ed25519", signature)
            bundle.writestr("public_key.pem", public_bytes)
            bundle.write(artifact_path, f"model/{artifact_path.name}")
        verify_model_package(temporary_path, trusted_public_key=public_bytes)
        os.replace(temporary_path, final_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return (
        final_path,
        manifest,
        _sha256_file(final_path),
        base64.b64encode(signature).decode("ascii"),
        key_id,
    )


def verify_model_package(
    package_path: str | Path,
    *,
    trusted_public_key: bytes | None = None,
    expected_package_hash: str = "",
) -> dict:
    path = Path(package_path).resolve()
    if not path.is_file():
        raise ValidationError("模型包不存在。")
    if expected_package_hash and _sha256_file(path) != expected_package_hash:
        raise ValidationError("模型包文件校验失败。")
    try:
        with zipfile.ZipFile(path, mode="r") as bundle:
            names = set(bundle.namelist())
            required = {"manifest.json", "signature.ed25519", "public_key.pem"}
            if not required.issubset(names):
                raise ValidationError("模型包缺少清单或签名文件。")
            if any(
                name.startswith(("/", "\\")) or ".." in Path(name).parts
                for name in names
            ):
                raise ValidationError("模型包包含不安全的文件路径。")
            manifest_bytes = bundle.read("manifest.json")
            signature = bundle.read("signature.ed25519")
            bundled_public_key = bundle.read("public_key.pem")
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            artifact_name = str((manifest.get("artifact") or {}).get("filename") or "")
            artifact_entry = f"model/{artifact_name}"
            if not artifact_name or artifact_entry not in names:
                raise ValidationError("模型包缺少模型文件。")
            artifact_bytes = bundle.read(artifact_entry)
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError("模型包格式不正确。") from exc

    public_bytes = trusted_public_key or bundled_public_key
    if trusted_public_key and bundled_public_key != trusted_public_key:
        raise ValidationError("模型包签名公钥与学校登记公钥不一致。")
    public_key = serialization.load_pem_public_key(public_bytes)
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValidationError("模型包签名公钥格式不正确。")
    try:
        public_key.verify(signature, manifest_bytes)
    except InvalidSignature as exc:
        raise ValidationError("模型包签名验证失败。") from exc
    expected_artifact_hash = str((manifest.get("artifact") or {}).get("sha256") or "")
    if _sha256_bytes(artifact_bytes) != expected_artifact_hash:
        raise ValidationError("模型包内模型文件校验失败。")
    if (manifest.get("signing") or {}).get("key_id") != _public_key_id(public_bytes):
        raise ValidationError("模型包签名密钥编号不一致。")
    return manifest


def _failed_audit(*, run, actor, action: str, message: str):
    if run is None or actor is None:
        return
    ModelReleaseAudit.objects.create(
        school=run.school,
        subject=run.subject,
        calibration_run=run,
        actor=actor,
        action=action,
        result=ModelReleaseAudit.Result.FAILED,
        message=message[:500],
        details={"calibration_run_id": run.id},
    )


def _decision_scope(run: ClassCalibrationRun) -> Q:
    scope = Q()
    for student_id, course_id in StratificationDecision.objects.filter(
        calibration_run=run
    ).values_list("student_id", "course_id"):
        scope |= Q(student_id=student_id, course_id=course_id)
    return scope


def _activate_release_suggestions(
    *, run: ClassCalibrationRun, note: str
) -> None:
    scope = _decision_scope(run)
    if not scope.children:
        return
    now = timezone.now()
    StratificationDecision.objects.filter(
        scope,
        status=StratificationDecision.Status.PENDING,
    ).exclude(calibration_run=run).update(
        status=StratificationDecision.Status.DEFERRED,
        review_note=f"{SYSTEM_RELEASE_NOTE_PREFIX}{note}",
        reviewed_at=now,
    )
    StratificationDecision.objects.filter(
        calibration_run=run,
        status=StratificationDecision.Status.DEFERRED,
        review_note__startswith=SYSTEM_RELEASE_NOTE_PREFIX,
    ).update(
        status=StratificationDecision.Status.PENDING,
        review_note="",
        reviewed_at=None,
    )


def publish_model_candidate(
    *, calibration_run: ClassCalibrationRun, actor
) -> ModelRelease:
    package_path = None
    try:
        with transaction.atomic():
            School.objects.select_for_update().get(pk=calibration_run.school_id)
            run = (
                ClassCalibrationRun.objects.select_for_update()
                .select_related("school", "subject", "dataset", "comparison_run")
                .get(pk=calibration_run.pk)
            )
            existing = ModelRelease.objects.filter(calibration_run=run).first()
            if existing:
                return existing
            _validate_candidate(run)
            is_test_data = bool(run.dataset.synthetic_run_id)
            active = (
                ModelRelease.objects.select_for_update()
                .filter(
                    school=run.school,
                    subject=run.subject,
                    is_test_data=is_test_data,
                    status=ModelRelease.Status.ACTIVE,
                )
                .first()
            )
            latest_version = (
                ModelRelease.objects.filter(
                    school=run.school,
                    subject=run.subject,
                    is_test_data=is_test_data,
                ).aggregate(value=Max("release_version"))["value"]
                or 0
            )
            release_version = latest_version + 1
            (
                package_path,
                manifest,
                package_hash,
                package_signature,
                key_id,
            ) = _build_package(run=run, release_version=release_version)
            if active:
                ModelRelease.objects.filter(pk=active.pk).update(
                    status=ModelRelease.Status.SUPERSEDED,
                    deactivated_at=timezone.now(),
                )
            release = ModelRelease.objects.create(
                release_key=canonical_hash(
                    {
                        "calibration_run": str(run.run_id),
                        "release_version": release_version,
                        "package_id": manifest["package_id"],
                    }
                )[:64],
                school=run.school,
                subject=run.subject,
                calibration_run=run,
                release_version=release_version,
                status=ModelRelease.Status.ACTIVE,
                is_test_data=is_test_data,
                previous_release=active,
                package_path=str(package_path),
                package_hash=package_hash,
                package_signature=package_signature,
                signing_key_id=key_id,
                manifest=manifest,
                released_by=actor,
            )
            _activate_release_suggestions(
                run=run,
                note=f"已由模型 v{release_version} 替代。",
            )
            ModelReleaseAudit.objects.create(
                school=run.school,
                subject=run.subject,
                calibration_run=run,
                release=release,
                actor=actor,
                action=ModelReleaseAudit.Action.PUBLISH,
                result=ModelReleaseAudit.Result.SUCCEEDED,
                message="候选模型已发布。",
                details={
                    "release_version": release_version,
                    "previous_release_id": active.id if active else None,
                    "package_hash": package_hash,
                    "is_test_data": is_test_data,
                },
            )
            return release
    except Exception as exc:
        if package_path is not None:
            Path(package_path).unlink(missing_ok=True)
        _failed_audit(
            run=calibration_run,
            actor=actor,
            action=ModelReleaseAudit.Action.PUBLISH,
            message=str(exc),
        )
        raise


def rollback_model_release(*, target: ModelRelease, actor) -> ModelRelease:
    try:
        with transaction.atomic():
            School.objects.select_for_update().get(pk=target.school_id)
            target = (
                ModelRelease.objects.select_for_update()
                .select_related("calibration_run", "school", "subject")
                .get(pk=target.pk)
            )
            current = (
                ModelRelease.objects.select_for_update()
                .filter(
                    school=target.school,
                    subject=target.subject,
                    is_test_data=target.is_test_data,
                    status=ModelRelease.Status.ACTIVE,
                )
                .first()
            )
            if current and current.pk == target.pk:
                return target
            _, public_path = _key_paths()
            if not public_path.exists():
                raise ValidationError("学校模型签名公钥不存在，不能回滚。")
            verify_model_package(
                target.package_path,
                trusted_public_key=public_path.read_bytes(),
                expected_package_hash=target.package_hash,
            )
            if current:
                ModelRelease.objects.filter(pk=current.pk).update(
                    status=ModelRelease.Status.ROLLED_BACK,
                    deactivated_at=timezone.now(),
                )
            ModelRelease.objects.filter(pk=target.pk).update(
                status=ModelRelease.Status.ACTIVE,
                deactivated_at=None,
            )
            target.refresh_from_db()
            _activate_release_suggestions(
                run=target.calibration_run,
                note=f"已回滚到模型 v{target.release_version}。",
            )
            ModelReleaseAudit.objects.create(
                school=target.school,
                subject=target.subject,
                calibration_run=target.calibration_run,
                release=target,
                actor=actor,
                action=ModelReleaseAudit.Action.ROLLBACK,
                result=ModelReleaseAudit.Result.SUCCEEDED,
                message="已回滚到指定模型版本。",
                details={
                    "target_release_id": target.id,
                    "replaced_release_id": current.id if current else None,
                    "package_hash": target.package_hash,
                },
            )
            return target
    except Exception as exc:
        _failed_audit(
            run=target.calibration_run,
            actor=actor,
            action=ModelReleaseAudit.Action.ROLLBACK,
            message=str(exc),
        )
        raise


def verify_model_release(*, release: ModelRelease, actor=None) -> dict:
    _, public_path = _key_paths()
    if not public_path.exists():
        raise ValidationError("学校模型签名公钥不存在。")
    try:
        manifest = verify_model_package(
            release.package_path,
            trusted_public_key=public_path.read_bytes(),
            expected_package_hash=release.package_hash,
        )
    except Exception as exc:
        if actor:
            _failed_audit(
                run=release.calibration_run,
                actor=actor,
                action=ModelReleaseAudit.Action.VERIFY,
                message=str(exc),
            )
        raise
    if actor:
        ModelReleaseAudit.objects.create(
            school=release.school,
            subject=release.subject,
            calibration_run=release.calibration_run,
            release=release,
            actor=actor,
            action=ModelReleaseAudit.Action.VERIFY,
            result=ModelReleaseAudit.Result.SUCCEEDED,
            message="模型包签名和文件校验通过。",
            details={"package_hash": release.package_hash},
        )
    return manifest
