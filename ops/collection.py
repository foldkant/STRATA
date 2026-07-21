from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import PurePosixPath


MAX_COLLECTION_PACKAGE_SIZE = 1024 * 1024 * 1024
MAX_ARCHIVE_FILE_COUNT = 5000
MAX_ARCHIVE_UNCOMPRESSED_SIZE = 4 * 1024 * 1024 * 1024
MAX_MANIFEST_SIZE = 1024 * 1024


class CollectionPackageError(ValueError):
    pass


def validate_collection_upload(uploaded_file) -> None:
    filename = str(getattr(uploaded_file, "name", ""))
    if not filename.lower().endswith(".zip"):
        raise CollectionPackageError("只能上传 ZIP 数据采集包。")
    if int(getattr(uploaded_file, "size", 0) or 0) <= 0:
        raise CollectionPackageError("数据采集包不能为空。")
    if uploaded_file.size > MAX_COLLECTION_PACKAGE_SIZE:
        raise CollectionPackageError("数据采集包不能超过 1GB。")


def sha256_file(file_obj) -> str:
    hasher = hashlib.sha256()
    for chunk in file_obj.chunks():
        hasher.update(chunk)
    file_obj.seek(0)
    return hasher.hexdigest()


def _safe_archive_name(name: str) -> bool:
    normalized = str(name or "").replace("\\", "/")
    path = PurePosixPath(normalized)
    first_part = path.parts[0] if path.parts else ""
    return (
        bool(normalized)
        and "\x00" not in normalized
        and not normalized.startswith("/")
        and ":" not in first_part
        and ".." not in path.parts
    )


def inspect_collection_package(file_obj) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    manifest: dict = {}
    file_count = 0
    uncompressed_size = 0

    try:
        with zipfile.ZipFile(file_obj) as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            file_count = len(files)
            uncompressed_size = sum(int(item.file_size or 0) for item in files)
            if file_count > MAX_ARCHIVE_FILE_COUNT:
                errors.append(f"压缩包文件数量超过 {MAX_ARCHIVE_FILE_COUNT} 个。")
            if uncompressed_size > MAX_ARCHIVE_UNCOMPRESSED_SIZE:
                errors.append("压缩包解压后总大小超过 4GB。")
            unsafe_names = [item.filename for item in files if not _safe_archive_name(item.filename)]
            if unsafe_names:
                errors.append("压缩包包含不安全的文件路径。")
            if any(item.flag_bits & 0x1 for item in files):
                errors.append("数据采集包不能包含加密文件。")

            manifest_info = next(
                (item for item in files if item.filename.replace("\\", "/") == "manifest.json"),
                None,
            )
            if manifest_info is None:
                errors.append("数据采集包缺少根目录 manifest.json。")
            elif manifest_info.file_size > MAX_MANIFEST_SIZE:
                errors.append("manifest.json 不能超过 1MB。")
            elif not errors:
                try:
                    with archive.open(manifest_info) as manifest_file:
                        manifest = json.loads(manifest_file.read().decode("utf-8"))
                    if not isinstance(manifest, dict):
                        errors.append("manifest.json 顶层必须是 JSON 对象。")
                        manifest = {}
                except UnicodeDecodeError:
                    errors.append("manifest.json 必须使用 UTF-8 编码。")
                except json.JSONDecodeError:
                    errors.append("manifest.json 不是有效的 JSON。")
    except zipfile.BadZipFile:
        errors.append("上传文件不是有效的 ZIP 压缩包。")
    except OSError as exc:
        errors.append(f"无法读取数据采集包：{exc}")
    finally:
        try:
            file_obj.seek(0)
        except (AttributeError, OSError):
            pass

    school_code = str(manifest.get("school_code") or "").strip()
    system_version = str(manifest.get("system_version") or "").strip()
    if manifest and not school_code:
        errors.append("manifest.json 缺少 school_code。")
    if manifest and not system_version:
        errors.append("manifest.json 缺少 system_version。")
    if manifest and not manifest.get("exported_at"):
        warnings.append("manifest.json 未提供 exported_at，无法核对学校导出时间。")
    if manifest and not manifest.get("schema_version"):
        warnings.append("manifest.json 未提供 schema_version，将按兼容格式登记。")

    return {
        "manifest": manifest,
        "errors": errors,
        "warnings": warnings,
        "file_count": file_count,
        "uncompressed_size": uncompressed_size,
    }
