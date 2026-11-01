"""Single-page UI loader; sources live in ``ui_src`` and build to ``ui_bundle.html``."""

from __future__ import annotations

import json
from pathlib import Path

TOKEN_PLACEHOLDER = "__SS_LOCAL_TOKEN_PLACEHOLDER__"
UI_HTML = Path(__file__).with_name("ui_bundle.html").read_text(encoding="utf-8")


def render_html(local_token: str = "") -> str:
    """Return the bundled UI with a safely encoded local admin token."""
    literal = json.dumps(local_token).replace("<", "\\u003c")
    return UI_HTML.replace(TOKEN_PLACEHOLDER, literal)
