from __future__ import annotations

import argparse
import string
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "tmp" / "lxgw-wenkai-lite-v1.522"
DEFAULT_OUTPUT = (
    ROOT
    / "static"
    / "fonts"
    / "lxgw-wenkai-lite-v1.522"
    / "admin-subset"
)
UI_SUFFIXES = {".html", ".js", ".ts", ".tsx", ".vue"}
UI_PUNCTUATION = "，。；：！？（）【】《》“”‘’·—…、￥℃±×÷→←↑↓"


def ui_text() -> str:
    characters = set(string.printable)
    characters.update(UI_PUNCTUATION)
    for path in (ROOT / "frontend" / "src").rglob("*"):
        if path.is_file() and path.suffix.lower() in UI_SUFFIXES:
            characters.update(path.read_text(encoding="utf-8"))
    return "".join(sorted(characters))


def rename_font(font: TTFont, style: str) -> None:
    family = "STRATA WenKai UI"
    full_name = f"{family} {style}"
    postscript_name = f"STRATAWenKaiUI-{style}"
    replacements = {
        1: family,
        2: style,
        3: f"{full_name}; LXGW WenKai Lite v1.522 UI subset",
        4: full_name,
        6: postscript_name,
        16: family,
        17: style,
    }
    name_table = font["name"]
    for record in name_table.names:
        replacement = replacements.get(record.nameID)
        if replacement is None:
            continue
        try:
            record.string = replacement.encode(record.getEncoding())
        except (LookupError, UnicodeEncodeError):
            record.string = replacement.encode("utf-16-be")


def build_subset(source: Path, destination: Path, style: str, text: str) -> None:
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.notdef_glyph = True
    options.notdef_outline = True
    options.recommended_glyphs = True

    font = TTFont(source)
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=text)
    subsetter.subset(font)
    rename_font(font, style)
    destination.parent.mkdir(parents=True, exist_ok=True)
    font.save(destination)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the locally hosted STRATA administrator UI font subsets."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    text = ui_text()
    builds = (
        ("LXGWWenKaiLite-Regular.ttf", "STRATAWenKaiUI-Regular.woff2", "Regular"),
        ("LXGWWenKaiLite-Medium.ttf", "STRATAWenKaiUI-Medium.woff2", "Medium"),
    )
    for source_name, output_name, style in builds:
        source = args.source_dir / source_name
        if not source.exists():
            raise FileNotFoundError(
                f"Missing official source font: {source}. See static/fonts/"
                "lxgw-wenkai-lite-v1.522/SOURCE.md for the release URL."
            )
        build_subset(source, args.output_dir / output_name, style, text)


if __name__ == "__main__":
    main()
