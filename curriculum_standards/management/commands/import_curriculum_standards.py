from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from curriculum_standards.models import (
    CurriculumDocumentType,
    CurriculumExtractionStatus,
    CurriculumStandard,
    CurriculumVersionStatus,
    SchoolStage,
)
from curriculum_standards.services import (
    create_version_from_existing_file,
    reprocess_version_text,
    sha256_file,
)


COMPULSORY_SUBJECTS = {
    "00_curriculum_plan": ("", "", CurriculumDocumentType.CURRICULUM_PLAN),
    "01_morality_and_rule_of_law": ("morality_and_rule_of_law", "道德与法治", CurriculumDocumentType.SUBJECT_STANDARD),
    "02_chinese": ("chinese", "语文", CurriculumDocumentType.SUBJECT_STANDARD),
    "03_history": ("history", "历史", CurriculumDocumentType.SUBJECT_STANDARD),
    "04_mathematics": ("mathematics", "数学", CurriculumDocumentType.SUBJECT_STANDARD),
    "05_english": ("english", "英语", CurriculumDocumentType.SUBJECT_STANDARD),
    "06_japanese": ("japanese", "日语", CurriculumDocumentType.SUBJECT_STANDARD),
    "07_russian": ("russian", "俄语", CurriculumDocumentType.SUBJECT_STANDARD),
    "08_geography": ("geography", "地理", CurriculumDocumentType.SUBJECT_STANDARD),
    "09_science": ("science", "科学", CurriculumDocumentType.SUBJECT_STANDARD),
    "10_physics": ("physics", "物理", CurriculumDocumentType.SUBJECT_STANDARD),
    "11_chemistry": ("chemistry", "化学", CurriculumDocumentType.SUBJECT_STANDARD),
    "12_biology": ("biology", "生物学", CurriculumDocumentType.SUBJECT_STANDARD),
    "13_information_technology": ("information_technology", "信息科技", CurriculumDocumentType.SUBJECT_STANDARD),
    "14_physical_education_and_health": ("physical_education_and_health", "体育与健康", CurriculumDocumentType.SUBJECT_STANDARD),
    "15_arts": ("arts", "艺术", CurriculumDocumentType.SUBJECT_STANDARD),
    "16_labor": ("labor", "劳动", CurriculumDocumentType.SUBJECT_STANDARD),
}

HIGH_SCHOOL_SUBJECT_CODES = {
    "语文": "chinese",
    "数学": "mathematics",
    "英语": "english",
    "思想政治": "ideological_and_political_education",
    "历史": "history",
    "地理": "geography",
    "物理": "physics",
    "化学": "chemistry",
    "生物学": "biology",
    "信息技术": "information_technology",
    "信息科技": "information_technology",
    "通用技术": "general_technology",
    "艺术": "arts",
    "音乐": "music",
    "美术": "fine_arts",
    "体育与健康": "physical_education_and_health",
    "日语": "japanese",
    "俄语": "russian",
    "德语": "german",
    "法语": "french",
    "西班牙语": "spanish",
}


@dataclass(frozen=True)
class Asset:
    path: Path
    stage: str
    document_type: str
    subject_code: str
    subject_name: str
    record_title: str
    official_title: str
    version_label: str
    publication_year: int
    source_url: str
    source_note: str


def _compulsory_assets(root: Path) -> list[Asset]:
    folder = root / "K1-K9" / "2022"
    result = []
    for path in sorted(folder.glob("*.pdf")):
        definition = COMPULSORY_SUBJECTS.get(path.stem)
        if definition is None:
            continue
        subject_code, subject_name, document_type = definition
        if document_type == CurriculumDocumentType.CURRICULUM_PLAN:
            official_title = "义务教育课程方案（2022年版）"
            record_title = official_title
        else:
            official_title = f"义务教育{subject_name}课程标准（2022年版）"
            record_title = official_title
        result.append(
            Asset(
                path=path,
                stage=SchoolStage.COMPULSORY,
                document_type=document_type,
                subject_code=subject_code,
                subject_name=subject_name,
                record_title=record_title,
                official_title=official_title,
                version_label="2022",
                publication_year=2022,
                source_url="http://www.moe.gov.cn/srcsite/A26/s8001/202204/t20220420_619921.html",
                source_note="教育部发布的义务教育课程方案和课程标准（2022年版）。",
            )
        )
    return result


def _high_school_identity(path: Path, year: int):
    title = re.sub(r"^\d+\.", "", path.stem)
    if "课程方案" in title:
        return (
            CurriculumDocumentType.CURRICULUM_PLAN,
            "",
            "",
            "普通高中课程方案",
            title,
        )
    match = re.search(r"普通高中(.+?)课程标准", title)
    if not match:
        return None
    official_subject_name = match.group(1)
    subject_code = HIGH_SCHOOL_SUBJECT_CODES.get(official_subject_name)
    if subject_code is None:
        return None
    subject_name = (
        "信息科技"
        if subject_code == "information_technology" and year >= 2025
        else official_subject_name
    )
    official_title = title
    if subject_code == "information_technology" and year >= 2025:
        official_title = title.replace("信息技术", "信息科技")
    record_subject_name = (
        "信息科技" if subject_code == "information_technology" else subject_name
    )
    return (
        CurriculumDocumentType.SUBJECT_STANDARD,
        subject_code,
        record_subject_name,
        f"普通高中{record_subject_name}课程标准",
        official_title,
    )


def _high_school_assets(root: Path, year: int) -> list[Asset]:
    folder = root / "K10-K12" / str(year)
    result = []
    for path in sorted(folder.glob("*.pdf")):
        identity = _high_school_identity(path, year)
        if identity is None:
            continue
        document_type, subject_code, subject_name, record_title, official_title = identity
        source_url = (
            "https://jnsyz.jinan-edu.cn/col/col422/index.html"
            if year == 2025
            else ""
        )
        source_note = (
            "济南市教育资源网站发布的普通高中课程标准日常修订版。"
            if year == 2025
            else (
                "项目所有者提供的教育部正式文件；原始本地目录为“普通高中课程方案及20科课程标准"
                "（2017年版2020年修订）”。"
            )
        )
        if year == 2025 and subject_code == "information_technology":
            source_note += (
                " PDF 封面正式题名使用“信息科技”，本地源文件名仍含“信息技术”。"
            )
        result.append(
            Asset(
                path=path,
                stage=SchoolStage.SENIOR_HIGH,
                document_type=document_type,
                subject_code=subject_code,
                subject_name=subject_name,
                record_title=record_title,
                official_title=official_title,
                version_label=f"2017-{year}",
                publication_year=year,
                source_url=source_url,
                source_note=source_note,
            )
        )
    return result


class Command(BaseCommand):
    help = "登记本地课程标准 PDF，并生成逐页文本、结构化内容候选和校验码。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--root",
            default=str(Path(settings.MEDIA_ROOT) / "curriculum_standards" / "official"),
            help="课程标准 official 目录。",
        )
        parser.add_argument(
            "--actor",
            default="superadmin",
            help="承担本次导入责任的超级管理员用户名。",
        )
        parser.add_argument(
            "--subject-code",
            action="append",
            dest="subject_codes",
            help="只处理指定 canonical 学科代码，可重复使用。",
        )
        parser.add_argument(
            "--ocr",
            action="store_true",
            help="对无内嵌文字的选中文档执行 OCR；建议与 --subject-code 配合。",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只列出将处理的权威版本，不写数据库。",
        )

    def handle(self, *args, **options):
        root = Path(options["root"]).resolve()
        media_root = Path(settings.MEDIA_ROOT).resolve()
        if not root.exists():
            raise CommandError(f"课程标准目录不存在：{root}")
        try:
            root.relative_to(media_root)
        except ValueError as exc:
            raise CommandError("课程标准目录必须位于 MEDIA_ROOT 内。") from exc

        User = get_user_model()
        actor = (
            User.objects.filter(username=options["actor"])
            .filter(Q(is_superuser=True) | Q(role="super_admin"))
            .first()
        )
        if actor is None:
            raise CommandError("未找到指定的超级管理员账号。")

        assets = [
            *_compulsory_assets(root),
            *_high_school_assets(root, 2020),
            *_high_school_assets(root, 2025),
        ]
        filters = set(options.get("subject_codes") or [])
        if filters:
            assets = [asset for asset in assets if asset.subject_code in filters]
        if options["dry_run"]:
            for asset in assets:
                self.stdout.write(
                    f"{asset.stage} {asset.subject_code or 'curriculum_plan'} "
                    f"{asset.version_label} {asset.path.name}"
                )
            self.stdout.write(self.style.SUCCESS(f"共 {len(assets)} 个权威版本；未扫描 current 目录。"))
            return

        created_count = 0
        reprocessed_count = 0
        skipped_count = 0
        for asset in assets:
            standard, created = CurriculumStandard.objects.get_or_create(
                school_stage=asset.stage,
                document_type=asset.document_type,
                subject_code=asset.subject_code,
                defaults={
                    "title": asset.record_title,
                    "subject_name": asset.subject_name,
                    "created_by": actor,
                    "updated_by": actor,
                },
            )
            if not created and (
                standard.title != asset.record_title
                or standard.subject_name != asset.subject_name
            ):
                standard.title = asset.record_title
                standard.subject_name = asset.subject_name
                standard.updated_by = actor
                standard.save()

            existing = standard.versions.filter(version_label=asset.version_label).first()
            if existing:
                with asset.path.open("rb") as raw:
                    asset_hash = sha256_file(raw)
                if existing.pdf_sha256 != asset_hash:
                    raise CommandError(
                        f"版本 {asset.version_label} 的本地 PDF 已变化：{asset.path.name}。"
                        "系统不会覆盖历史版本，请先核实并使用新的版本标识。"
                    )
                if (
                    options["ocr"]
                    and existing.status == CurriculumVersionStatus.DRAFT
                    and existing.extraction_status != CurriculumExtractionStatus.COMPLETED
                ):
                    reprocess_version_text(
                        existing,
                        actor=actor,
                        enable_ocr=True,
                    )
                    reprocessed_count += 1
                    self.stdout.write(f"OCR：{asset.official_title}")
                else:
                    skipped_count += 1
                continue

            replaces = standard.versions.order_by("-publication_year", "-id").first()
            version = create_version_from_existing_file(
                standard=standard,
                file_path=asset.path,
                media_root=media_root,
                version_label=asset.version_label,
                publication_year=asset.publication_year,
                effective_year=asset.publication_year,
                issued_by="中华人民共和国教育部",
                source_url=asset.source_url,
                official_title=asset.official_title,
                source_note=asset.source_note,
                replaces_version=replaces,
                enable_ocr=bool(options["ocr"]),
                actor=actor,
            )
            created_count += 1
            self.stdout.write(
                f"登记：{version.official_title} [{version.extraction_status}]"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"完成：新增 {created_count}，OCR/重处理 {reprocessed_count}，跳过 {skipped_count}。"
                "所有新版本保持草稿，需由超级管理员复核后发布。"
            )
        )
