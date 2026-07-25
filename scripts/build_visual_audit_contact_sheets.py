"""Build first-viewport contact sheets from the Playwright verification screenshots."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "platform-audit-2026-07-24" / "verification-screenshots"
OUTPUT = ROOT / "docs" / "platform-audit-2026-07-24" / "verification-contact-sheets"
VIEWPORTS = {
    "desktop-1440": (1440, 900),
    "tablet-768": (768, 1024),
    "mobile-390": (390, 844),
}


def build_sheet(viewport_name: str, role_dir: Path) -> Path | None:
    screenshots = sorted(role_dir.glob("*.png"))
    if role_dir.name == "teacher":
        # Route IDs are configurable in the audit. Keep only the newest captured
        # lesson and classroom instance so an older verification run cannot make
        # the current contact sheet look like a mixed-version interface.
        for prefix, suffix in (
            ("teacher-lessons-", "-design.png"),
            ("teacher-classroom-", ".png"),
        ):
            route_captures = [
                path for path in screenshots
                if path.name.startswith(prefix) and path.name.endswith(suffix)
            ]
            if len(route_captures) > 1:
                newest = max(route_captures, key=lambda path: path.stat().st_mtime_ns)
                screenshots = [
                    path for path in screenshots
                    if path not in route_captures or path == newest
                ]
    if not screenshots:
        return None

    viewport_width, viewport_height = VIEWPORTS[viewport_name]
    target_width = 360 if viewport_name == "desktop-1440" else 280
    target_height = round(viewport_height * target_width / viewport_width)
    label_height = 38
    columns = 3 if viewport_name == "desktop-1440" else 4
    rows = (len(screenshots) + columns - 1) // columns
    gap = 16
    sheet_width = columns * target_width + (columns + 1) * gap
    sheet_height = rows * (target_height + label_height) + (rows + 1) * gap
    sheet = Image.new("RGB", (sheet_width, sheet_height), "#edf1ed")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for index, screenshot_path in enumerate(screenshots):
        with Image.open(screenshot_path) as source:
            source = source.convert("RGB")
            crop = source.crop(
                (
                    0,
                    0,
                    min(source.width, viewport_width),
                    min(source.height, viewport_height),
                )
            )
            crop.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)
            tile = Image.new("RGB", (target_width, target_height), "white")
            tile.paste(
                crop,
                ((target_width - crop.width) // 2, (target_height - crop.height) // 2),
            )

        column = index % columns
        row = index // columns
        x = gap + column * (target_width + gap)
        y = gap + row * (target_height + label_height + gap)
        sheet.paste(tile, (x, y))
        label = screenshot_path.stem[:54]
        draw.text((x + 6, y + target_height + 10), label, fill="#263832", font=font)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    result = OUTPUT / f"{viewport_name}--{role_dir.name}.jpg"
    sheet.save(result, quality=88, optimize=True)
    return result


def main() -> None:
    results = []
    for viewport_name in VIEWPORTS:
        for role_dir in sorted((SOURCE / viewport_name).iterdir()):
            if role_dir.is_dir():
                result = build_sheet(viewport_name, role_dir)
                if result:
                    results.append(result)
    print(f"Built {len(results)} contact sheets in {OUTPUT}")


if __name__ == "__main__":
    main()
