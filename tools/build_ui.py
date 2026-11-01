"""Bundle the source UI assets into the self-contained HTML served by Python."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "superior_sync" / "ui_src"
OUTPUT = ROOT / "superior_sync" / "ui_bundle.html"


def build() -> str:
    template = (SOURCE / "index.html").read_text(encoding="utf-8")
    css = (SOURCE / "style.css").read_text(encoding="utf-8").strip()
    javascript = (SOURCE / "app.js").read_text(encoding="utf-8").strip()
    if template.count("<!--SS_STYLES-->") != 1:
        raise ValueError("UI template must contain exactly one style placeholder")
    if template.count("<!--SS_SCRIPT-->") != 1:
        raise ValueError("UI template must contain exactly one script placeholder")
    return (
        template.replace("<!--SS_STYLES-->", f"<style>\n{css}\n</style>")
        .replace("<!--SS_SCRIPT-->", f"<script>\n{javascript}\n</script>")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the checked-in bundle is stale instead of writing it",
    )
    args = parser.parse_args()
    generated = build()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != generated:
            parser.error("UI bundle is stale; run python tools/build_ui.py")
        return 0
    OUTPUT.write_text(generated, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
