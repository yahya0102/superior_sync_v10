# -*- coding: utf-8 -*-
"""Interactive command-line interface (``--mode cli`` / ``--mode all``).

The CLI mirrors the web UI's five views — Files, Peers, Conflicts, Status,
Settings — and shares its translation tables, so both front-ends speak the
same language and show the same data.
"""
from __future__ import annotations

import cmd
import contextlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import i18n
from .utils import human_size, log


# ==================================================================
# Terminal styling — auto-disables on non-TTY / NO_COLOR / dumb term
# ==================================================================

class Style:
    """ANSI styling with automatic detection and graceful degradation."""

    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"
    ITALIC = "\x1b[3m"
    UNDERLINE = "\x1b[4m"

    FG = {
        "black": "\x1b[30m", "red": "\x1b[31m", "green": "\x1b[32m",
        "yellow": "\x1b[33m", "blue": "\x1b[34m", "magenta": "\x1b[35m",
        "cyan": "\x1b[36m", "white": "\x1b[37m",
        "gray": "\x1b[90m", "bright_red": "\x1b[91m",
        "bright_green": "\x1b[92m", "bright_yellow": "\x1b[93m",
        "bright_blue": "\x1b[94m", "bright_magenta": "\x1b[95m",
        "bright_cyan": "\x1b[96m", "bright_white": "\x1b[97m",
    }

    enabled = True

    @classmethod
    def autodetect(cls) -> None:
        if os.environ.get("NO_COLOR"):
            cls.enabled = False
            return
        if os.environ.get("FORCE_COLOR"):
            cls.enabled = True
            return
        cls.enabled = sys.stdout.isatty() and os.environ.get("TERM", "") != "dumb"
        if os.name == "nt" and cls.enabled:
            with contextlib.suppress(Exception):
                import ctypes
                k = ctypes.windll.kernel32
                k.SetConsoleMode(k.GetStdHandle(-11), 7)

    # [FIX-MIN-13] ``Style.disable`` أُزيل: لم يكُن مُستخدَماً في أي
    # مكان.  ``autodetect`` هو المدخل الوحيد لضبط ``enabled``.

    @classmethod
    def wrap(cls, text: str, *codes: str) -> str:
        if not cls.enabled or not codes:
            return text
        return "".join(codes) + text + cls.RESET

    @classmethod
    def c(cls, text: Any, color: str, *extra: str) -> str:
        return cls.wrap(str(text), cls.FG.get(color, ""), *extra)

    @classmethod
    def bold(cls, text: Any) -> str:
        return cls.wrap(str(text), cls.BOLD)

    @classmethod
    def dim(cls, text: Any) -> str:
        return cls.wrap(str(text), cls.DIM)

    @classmethod
    def badge(cls, text: str, kind: str = "default") -> str:
        palette = {
            "default": "gray", "muted": "gray",
            "success": "bright_green", "ok": "bright_green",
            "warning": "bright_yellow", "warn": "bright_yellow",
            "danger": "bright_red", "error": "bright_red",
            "info": "bright_cyan", "primary": "bright_blue",
            "purple": "bright_magenta",
        }
        color = palette.get(kind, palette["default"])
        return cls.c(f" {text} ", color, cls.BOLD)


# ==================================================================
# Terminal utilities — width, alignment, table rendering, pager
# ==================================================================

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", str(s))


def display_width(s: str) -> int:
    return len(strip_ansi(str(s)))


def term_width(default: int = 100) -> int:
    try:
        return max(60, shutil.get_terminal_size((default, 24)).columns)
    except OSError:
        return default


def pad(s: str, width: int, align: str = "left") -> str:
    diff = width - display_width(s)
    if diff <= 0:
        return s
    if align == "right":
        return " " * diff + s
    if align == "center":
        left = diff // 2
        return " " * left + s + " " * (diff - left)
    return s + " " * diff


def truncate(s: str, width: int, ellipsis: str = "…") -> str:
    s = str(s)
    if display_width(s) <= width:
        return s
    if width <= len(ellipsis):
        return ellipsis[:width]
    return s[: width - len(ellipsis)] + ellipsis


def fit(s: str, width: int) -> str:
    return pad(truncate(s, width), width)


def clear_screen() -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.flush()
    else:
        print()


def render_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[Any]],
    aligns: Sequence[str] | None = None,
    max_width: int | None = None,
) -> str:
    """Render a Unicode-table with bold headers and auto-sized columns."""
    rows = [list(map(str, r)) for r in rows]
    aligns = list(aligns or ["left"] * len(headers))
    ncols = len(headers)

    widths = [display_width(h) for h in headers]
    for row in rows:
        for i in range(min(ncols, len(row))):
            widths[i] = max(widths[i], display_width(row[i]))

    limit = (max_width or term_width()) - (3 * (ncols - 1)) - 4
    total = sum(widths)
    if total > limit and widths:
        while sum(widths) > limit:
            idx = widths.index(max(widths))
            if widths[idx] <= 8:
                break
            widths[idx] -= 1

    top = "  ┌" + "─┬".join("─" * (w + 2) for w in widths) + "┐"
    mid = "  ├" + "─┼".join("─" * (w + 2) for w in widths) + "┤"
    bot = "  └" + "─┴".join("─" * (w + 2) for w in widths) + "┘"

    def fmt_row(cells, bold=False):
        parts = []
        for i, w in enumerate(widths):
            cell = cells[i] if i < len(cells) else ""
            cell = fit(cell, w)
            if bold:
                cell = Style.bold(cell)
            parts.append(" " + pad(cell, w, aligns[i]) + " ")
        return "  │" + "│".join(parts) + "│"

    out = [Style.dim(top)]
    out.append(fmt_row(headers, bold=True))
    out.append(Style.dim(mid))
    if not rows:
        out.append("  │ " + pad("(empty)", sum(widths) + 3 * (ncols - 1),
                                "center") + " │")
    else:
        for row in rows:
            out.append(fmt_row(row))
    out.append(Style.dim(bot))
    return "\n".join(out)


def render_kv(pairs: Iterable[tuple[str, Any]], indent: int = 2) -> str:
    """Render an aligned key/value block (mini definition list)."""
    pairs = [(str(k), "" if v is None else str(v)) for k, v in pairs]
    if not pairs:
        return ""
    width = max(display_width(k) for k, _ in pairs)
    pad_s = " " * indent
    return "\n".join(
        f"{pad_s}{Style.dim(k.ljust(width))}  {v}" for k, v in pairs
    )


def section(title: str, subtitle: str = "") -> str:
    line = "─" * max(4, term_width() - 4)
    head = f"\n  {Style.bold(title)}"
    if subtitle:
        head += "  " + Style.dim(subtitle)
    return f"{head}\n  {Style.dim(line)}"


def page(text: str) -> None:
    """Print text, paging through $PAGER / less when output is long."""
    if not sys.stdout.isatty() or text.count("\n") < 30:
        print(text)
        return
    pager = os.environ.get("PAGER") or shutil.which("less") or shutil.which("more")
    if not pager:
        print(text)
        return
    try:
        args = [pager]
        if os.path.basename(pager).startswith("less"):
            args += ["-FRX"]
        subprocess.run(args, input=text.encode("utf-8"), check=False)
    except (OSError, subprocess.SubprocessError):
        print(text)


# ==================================================================
# CLI strings — kept beside the class so translations stay self-contained
# ==================================================================

_CLI_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "banner.title": "Superior Sync · interactive shell",
        "banner.hint": "Type 'help' for commands, 'help <cmd>' for details, Ctrl-D to exit.",
        "empty.peers": "(no peers)",
        "empty.files": "(no files)",
        "empty.conflicts": "(none)",
        "empty.trash": "(trash is empty)",
        "empty.versions": "(no versions)",
        "err.unknown": "Unknown command: {cmd!r} (try 'help')",
        "err.usage": "usage: {usage}",
        "err.parse": "Parse error: {err}",
        "err.missing": "Not found: {what}",
        "err.engine_stopped": "Engine is stopped (use 'start' first).",
        "confirm.yes": "yes",
        "confirm.no": "no",
        "prompt.confirm": "Are you sure? [y/N] ",
        "prompt.more": "… more — press Enter to continue, 'q' to stop ",
        "col.id": "ID", "col.name": "Name", "col.status": "Status",
        "col.address": "Address", "col.last_seen": "Last seen",
        "col.path": "Path", "col.size": "Size", "col.modified": "Modified",
        "col.share": "Share", "col.detected": "Detected",
        "col.key": "Key", "col.value": "Value",
        "status.engine": "engine", "status.node": "node",
        "status.watcher": "watcher", "status.peers_online": "peers online",
        "status.files": "indexed files", "status.sent": "sent",
        "status.received": "received", "status.conflicts": "conflicts",
        "status.uptime": "uptime", "status.errors": "recent errors",
        "status.no_errors": "no recent errors",
        "status.running": "running", "status.stopped": "stopped",
        "status.online": "online", "status.offline": "offline",
        "lang.set": "Language switched to {lang}.",
        "lang.available": "Available languages: {langs}",
        "watch.started": "Watching every {interval}s — press Ctrl-C to stop.",
        "watch.stopped": "Stopped.",
        "settings.saved": "Setting '{key}' updated.",
        "settings.unknown": "Unknown setting: {key}",
        "settings.readonly": "Setting '{key}' is read-only.",
        "files.added": "Added: {path}",
        "files.removed": "Moved to trash: {path}",
        "files.permanent": "Permanently deleted: {path}",
        "files.uploaded": "Stored in share '{share}': {path}",
        "files.downloaded": "Saved to: {path}",
        "conflict.resolved": "Conflict {cid} resolved ({action}).",
        "conflict.not_found": "Conflict not found: {cid}",
        "version.restored": "Version {vid} restored.",
        "trash.restored": "Restored from trash: {path}",
        "trash.emptied": "Emptied {n} item(s).",
        "peer.added": "Peer added: {pid}",
        "peer.removed": "Peer removed: {pid}",
        "peer.not_found": "Peer not found: {pid}",
        "sync.triggered": "Sync scheduled for {share}.",
        "sync.all": "Sync scheduled for all shares.",
        "sync.stopped_engine": "Engine is stopped.",
        "engine.started": "Engine started.",
        "engine.stopped": "Engine stopped.",
        "engine.already": "Engine is already {state}.",
        "folder.added": "Folder added: {path}",
        "folder.removed": "Folder removed: {path}",
        "folder.not_found": "Folder not found: {path}",
        "json.invalid": "Cannot parse JSON value: {err}",
        "shell.hint": "Entering a system shell — type 'exit' to return.",
        "shell.returned": "Back in the Superior Sync shell.",
        "open.launched": "Opening web UI at {url} …",
        "hint.json": "Add --json to get machine-readable output.",
        "help.title": "Superior Sync — command reference",
        "help.groups": "Information", "help.actions": "Actions",
        "help.control": "Control", "help.meta": "Shell",
    },
    "ar": {
        "banner.title": "Superior Sync · صدفة تفاعلية",
        "banner.hint": "اكتب 'help' للأوامر، 'help <cmd>' للتفاصيل، Ctrl-D للخروج.",
        "empty.peers": "(لا نظراء)",
        "empty.files": "(لا ملفات)",
        "empty.conflicts": "(لا شيء)",
        "empty.trash": "(السلة فارغة)",
        "empty.versions": "(لا إصدارات)",
        "err.unknown": "أمر غير معروف: {cmd!r} (جرّب 'help')",
        "err.usage": "الاستخدام: {usage}",
        "err.parse": "خطأ في التحليل: {err}",
        "err.missing": "غير موجود: {what}",
        "err.engine_stopped": "المحرك متوقف (استخدم 'start' أولاً).",
        "confirm.yes": "نعم", "confirm.no": "لا",
        "prompt.confirm": "هل أنت متأكد؟ [y/N] ",
        "prompt.more": "… المزيد — اضغط Enter للمتابعة، 'q' للتوقف ",
        "col.id": "المعرّف", "col.name": "الاسم", "col.status": "الحالة",
        "col.address": "العنوان", "col.last_seen": "آخر ظهور",
        "col.path": "المسار", "col.size": "الحجم", "col.modified": "آخر تعديل",
        "col.share": "المشاركة", "col.detected": "تاريخ الاكتشاف",
        "col.key": "المفتاح", "col.value": "القيمة",
        "status.engine": "المحرك", "status.node": "الجهاز",
        "status.watcher": "المراقب", "status.peers_online": "نظراء متصلون",
        "status.files": "ملفات مفهرسة", "status.sent": "مُرسل",
        "status.received": "مُستقبل", "status.conflicts": "تعارضات",
        "status.uptime": "مدة التشغيل", "status.errors": "آخر الأخطاء",
        "status.no_errors": "لا أخطاء حديثة",
        "status.running": "يعمل", "status.stopped": "متوقف",
        "status.online": "متصل", "status.offline": "غير متصل",
        "lang.set": "تم تغيير اللغة إلى {lang}.",
        "lang.available": "اللغات المتاحة: {langs}",
        "watch.started": "المتابعة كل {interval} ثانية — Ctrl-C للتوقف.",
        "watch.stopped": "تم الإيقاف.",
        "settings.saved": "تم تحديث الإعداد '{key}'.",
        "settings.unknown": "إعداد غير معروف: {key}",
        "settings.readonly": "الإعداد '{key}' للقراءة فقط.",
        "files.added": "أُضيف: {path}",
        "files.removed": "نُقل إلى السلة: {path}",
        "files.permanent": "حُذف نهائياً: {path}",
        "files.uploaded": "تم التخزين في المشاركة '{share}': {path}",
        "files.downloaded": "تم الحفظ في: {path}",
        "conflict.resolved": "حُل التعارض {cid} ({action}).",
        "conflict.not_found": "التعارض غير موجود: {cid}",
        "version.restored": "تمت استعادة الإصدار {vid}.",
        "trash.restored": "استُعيد من السلة: {path}",
        "trash.emptied": "أُفرِغت السلة من {n} عنصر.",
        "peer.added": "أُضيف النظير: {pid}",
        "peer.removed": "أُزيل النظير: {pid}",
        "peer.not_found": "النظير غير موجود: {pid}",
        "sync.triggered": "تم جدولة مزامنة {share}.",
        "sync.all": "تم جدولة مزامنة كل المشاركات.",
        "sync.stopped_engine": "المحرك متوقف.",
        "engine.started": "بدأ المحرك.",
        "engine.stopped": "توقف المحرك.",
        "engine.already": "المحرك بالفعل {state}.",
        "folder.added": "أُضيف المجلد: {path}",
        "folder.removed": "أُزيل المجلد: {path}",
        "folder.not_found": "المجلد غير موجود: {path}",
        "json.invalid": "تعذّر تحليل قيمة JSON: {err}",
        "shell.hint": "دخول إلى صدفة النظام — اكتب 'exit' للعودة.",
        "shell.returned": "رجعت إلى صدفة Superior Sync.",
        "open.launched": "جارٍ فتح الواجهة على {url} …",
        "hint.json": "أضف --json للحصول على مخرجات قابلة للقراءة آلياً.",
        "help.title": "Superior Sync — مرجع الأوامر",
        "help.groups": "معلومات", "help.actions": "إجراءات",
        "help.control": "تحكم", "help.meta": "الصدفة",
    },
}


def _t(key: str, **vars: Any) -> str:
    """Localized string for the CLI, falling back to the global i18n table."""
    lang = i18n.get_language() if i18n.get_language() in _CLI_STRINGS else "en"
    table = _CLI_STRINGS.get(lang) or _CLI_STRINGS["en"]
    text = table.get(key)
    if text is None:
        text = _CLI_STRINGS["en"].get(key, key)
    if vars:
        try:
            text = text.format(**vars)
        except (KeyError, IndexError):
            pass
    return text


# ==================================================================
# Readline integration (optional, silent on failure)
# ==================================================================

def _install_readline() -> Any:
    """Enable GNU readline (or pyreadline3) with a dedicated history file."""
    try:
        import readline  # type: ignore
    except ImportError:
        return None
    return readline


# ==================================================================
# Interactive shell
# ==================================================================

class CommandLineInterface(cmd.Cmd):
    """Interactive admin shell for :class:`SuperiorSyncApp`.

    Every command mirrors a view or action of the web UI, and output uses
    the same colour semantics (blue primary, green success, amber warning,
    red danger). Data is read from the live engine, so the terminal always
    reflects the current state of the running server.
    """

    prompt = "sync> "
    ruler = "─"
    doc_header = ""
    undoc_header = ""
    nohelp = ""
    maxcol = 78

    # ---------------------------------------------------------------
    # Initialization
    # ---------------------------------------------------------------

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.engine = app.engine
        self.config = app.config
        self._readline = _install_readline()
        # Defensive ``getattr`` so tests can pass a lightweight fake config
        # without a ``data_dir`` attribute.
        data_dir = getattr(self.config, "data_dir", None) or "."
        self._history_path = Path(data_dir) / "cli_history"
        self._setup_readline()

    # ---------------------------------------------------------------
    # Readline: history + tab completion
    # ---------------------------------------------------------------

    def _setup_readline(self) -> None:
        rl = self._readline
        if rl is None:
            return
        with contextlib.suppress(Exception):
            if self._history_path.exists():
                rl.read_history_file(str(self._history_path))
            rl.set_history_length(1000)
        with contextlib.suppress(Exception):
            rl.parse_and_bind("tab: complete")
        with contextlib.suppress(Exception):
            rl.set_completer_delims(" \t\n")

    def _save_history(self) -> None:
        rl = self._readline
        if rl is None:
            return
        with contextlib.suppress(Exception):
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            rl.write_history_file(str(self._history_path))

    # ---------------------------------------------------------------
    # Argument parsing helpers
    # ---------------------------------------------------------------

    def _args(self, arg: str) -> list[str]:
        try:
            return shlex.split(arg)
        except ValueError as exc:
            print(_t("err.parse", err=exc))
            return []

    @staticmethod
    def _split_flags(tokens: list[str]) -> tuple[dict[str, Any], list[str]]:
        flags: dict[str, Any] = {}
        positional: list[str] = []
        for tok in tokens:
            if tok.startswith("--"):
                body = tok[2:]
                if "=" in body:
                    k, v = body.split("=", 1)
                    flags[k] = v
                else:
                    flags[body] = True
            elif tok.startswith("-") and len(tok) == 2:
                flags[tok[1:]] = True
            else:
                positional.append(tok)
        return flags, positional

    def _print_json(self, payload: Any) -> None:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))

    def _confirm(self, prompt: str | None = None) -> bool:
        prompt = prompt or _t("prompt.confirm")
        try:
            return input(prompt).strip().lower() in ("y", "yes", "نعم")
        except EOFError:
            return False

    def _paginate(self, lines: list[str], page_size: int = 30) -> None:
        if not sys.stdout.isatty() or len(lines) <= page_size:
            print("\n".join(lines))
            return
        for i in range(0, len(lines), page_size):
            print("\n".join(lines[i: i + page_size]))
            if i + page_size >= len(lines):
                break
            try:
                key = input(_t("prompt.more")).strip().lower()
            except EOFError:
                break
            if key == "q":
                break

    # [FIX-MIN-13] ``_spinner`` أُزيل: لم يكُن مُستخدَماً في أي أمر.
    # كان يُوفّر مؤشر انتظار TTY لكن كل الأوامر الحالية سريعة بما يكفي
    # أو تطبع تقدّمها بنفسها.

    # ---------------------------------------------------------------
    # Shell lifecycle
    # ---------------------------------------------------------------

    def run_cli(self) -> None:
        Style.autodetect()
        self._print_banner()
        try:
            self.cmdloop()
        except (KeyboardInterrupt, EOFError):
            print()
        finally:
            self._save_history()

    def _print_banner(self) -> None:
        width = min(term_width(), 72)
        bar = "─" * width
        print()
        print("  " + Style.c(bar, "bright_blue"))
        print("  " + Style.bold(Style.c(f"  {_t('banner.title')}", "bright_white")))
        print("  " + Style.dim(f"  {_t('banner.hint')}"))
        print("  " + Style.c(bar, "bright_blue"))
        print()

    def emptyline(self) -> bool:
        return False

    def default(self, line: str) -> None:
        cmd = line.split(maxsplit=1)[0] if line else ""
        print(Style.c(_t("err.unknown", cmd=cmd), "bright_yellow"))

    def parseline(self, line: str) -> tuple[str | None, str | None, str]:
        """Support ``!shell`` syntax and comments starting with ``#``."""
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return None, None, line
        if stripped.startswith("!"):
            return "shell", stripped[1:].strip(), line
        return super().parseline(line)

    # ==================================================================
    # Views — mirror the web UI's five tabs
    # ==================================================================

    def do_status(self, arg: str) -> None:
        """status [--json] — engine state, counters and recent errors."""
        flags, _ = self._split_flags(self._args(arg))
        st = self.engine.get_stats()
        if "json" in flags:
            self._print_json(st)
            return

        tr = st["transfer"]
        uptime = st.get("sync_state", {}).get("started_at")
        errors = st.get("sync_state", {}).get("errors", [])[-3:]

        engine_state = _t("status.running" if self.engine.running else "status.stopped")
        engine_badge = Style.badge(engine_state,
                                   "success" if self.engine.running else "danger")

        print(section(_t("topbar.status.title"), _t("topbar.status.sub")))
        print(render_kv([
            (_t("status.engine"), engine_badge),
            (_t("status.node"),
             f"{st['node']['name']}  " + Style.dim(f"({st['node']['id']})")),
            (_t("status.watcher"), st.get("watcher_backend", "—")),
            (_t("status.peers_online"),
             Style.c(st["p2p_protocol"].get("peers_online", 0), "bright_cyan")),
            (_t("status.files"),
             Style.c(st.get("sync_records_count", 0), "bright_white")),
            (_t("status.sent"),
             Style.c(human_size(tr["bytes_sent"]), "bright_blue")),
            (_t("status.received"),
             Style.c(human_size(tr["bytes_received"]), "bright_green")),
            (_t("status.conflicts"),
             Style.c(tr.get("conflicts", 0),
                     "bright_red" if tr.get("conflicts") else "gray")),
            (_t("status.uptime"),
             self._human_duration(time.time() - uptime) if uptime else "—"),
        ]))
        print()
        if errors:
            print("  " + Style.bold(_t("status.errors")))
            for er in errors:
                when = time.strftime("%Y-%m-%d %H:%M",
                                     time.localtime(er.get("time", 0)))
                print(f"    {Style.dim(when)}  "
                      f"{Style.c(er.get('error', ''), 'bright_red')}")
        else:
            print("  " + Style.dim(_t("status.no_errors")))

    def do_files(self, arg: str) -> None:
        """files [SHARE] [FOLDER] [--json] — list files in a share."""
        flags, positional = self._split_flags(self._args(arg))
        shares = self.config.shares()
        share = positional[0] if positional else "received"
        folder = positional[1].strip("/") if len(positional) > 1 else ""

        if share not in shares:
            print(Style.c(_t("err.missing", what=share), "bright_red"))
            return

        like = (folder + "/%") if folder else "%"
        rows = self.engine.db.query(
            "SELECT path, size, mtime_ns FROM files "
            "WHERE share=? AND deleted=0 AND path LIKE ? ORDER BY path",
            (share, like),
        )
        if "json" in flags:
            self._print_json({"share": share, "folder": folder, "files": rows})
            return

        print(section(_t("topbar.files.title"),
                      f"{Style.dim('share')}={Style.c(share, 'bright_blue')} "
                      f"{Style.dim('folder')}={folder or '/'}"))
        if not rows:
            print("  " + Style.dim(_t("empty.files")))
            return

        table_rows = []
        for r in rows:
            name = r["path"].split("/")[-1]
            table_rows.append([
                name,
                human_size(r["size"] or 0),
                time.strftime("%Y-%m-%d %H:%M",
                              time.localtime((r["mtime_ns"] or 0) / 1e9)),
            ])
        print(render_table(
            [_t("col.name"), _t("col.size"), _t("col.modified")],
            table_rows,
            ["left", "right", "left"],
        ))
        print("  " + Style.dim(
            f"{len(rows)} " + ("files" if len(rows) != 1 else "file")))
        print("  " + Style.dim(_t("hint.json")))

    def do_shares(self, arg: str) -> None:
        """shares [--json] — list every share (received + sync folders)."""
        flags, _ = self._split_flags(self._args(arg))
        shares = self.config.shares()
        if "json" in flags:
            self._print_json(shares)
            return
        print(section(_t("files.col.share")))
        for sid, path in shares.items():
            style = "bright_blue" if sid == "received" else "bright_white"
            print(f"  {Style.c(sid.ljust(18), style)}  {Style.dim(path)}")

    def do_peers(self, arg: str) -> None:
        """peers [--json] — list known peers, mirroring /api/peers."""
        flags, _ = self._split_flags(self._args(arg))
        peers = self.engine.p2p_protocol.all_peers()
        if "json" in flags:
            self._print_json(peers)
            return

        print(section(_t("topbar.peers.title"), _t("topbar.peers.sub")))
        if not peers:
            print("  " + Style.dim(_t("empty.peers")))
            return

        rows = []
        for p in peers:
            online = bool(p.get("online"))
            status = Style.badge(
                _t("status.online") if online else _t("status.offline"),
                "success" if online else "danger",
            )
            last = p.get("last_seen") or 0
            rows.append([
                p["id"][:12],
                (p.get("name") or "—")[:24],
                f"{p['ip']}:{p['port']}",
                status,
                time.strftime("%H:%M:%S", time.localtime(last)) if last else "—",
            ])
        print(render_table(
            [_t("col.id"), _t("col.name"), _t("col.address"),
             _t("col.status"), _t("col.last_seen")],
            rows,
            ["left", "left", "left", "center", "right"],
        ))

    def do_conflicts(self, arg: str) -> None:
        """conflicts [--open] [--json] — list file conflicts."""
        flags, _ = self._split_flags(self._args(arg))
        only_open = bool(flags.get("open", False))
        rows = self.engine.conflict_resolver.list_conflicts(only_open=only_open)
        if "json" in flags:
            self._print_json(rows)
            return

        print(section(_t("topbar.conflicts.title"), _t("topbar.conflicts.sub")))
        if not rows:
            print("  " + Style.dim(_t("empty.conflicts")))
            return

        table_rows = []
        for r in rows:
            when = time.strftime("%Y-%m-%d %H:%M",
                                 time.localtime(r.get("detected_at", 0)))
            resolved = "✔" if r.get("resolved") else "●"
            color = "bright_green" if r.get("resolved") else "bright_yellow"
            table_rows.append([
                Style.c(r["id"][:8], "bright_white"),
                f"{r['share']}/{r['path']}",
                Style.c(resolved, color),
                when,
            ])
        print(render_table(
            [_t("col.id"), _t("col.path"), "●", _t("col.detected")],
            table_rows,
            ["left", "left", "center", "right"],
        ))

    def do_versions(self, arg: str) -> None:
        """versions [PATH] [--json] — list stored file versions."""
        flags, positional = self._split_flags(self._args(arg))
        path = positional[0] if positional else None
        rows = self.engine.conflict_resolver.get_file_versions(path)
        if "json" in flags:
            self._print_json(rows)
            return
        if not rows:
            print("  " + Style.dim(_t("empty.versions")))
            return
        table_rows = []
        for r in rows:
            table_rows.append([
                str(r["id"]),
                os.path.basename(r.get("file_path", "")),
                human_size(r.get("size", 0)),
                time.strftime("%Y-%m-%d %H:%M",
                              time.localtime(r.get("created_at", 0))),
                r.get("note", "") or "",
            ])
        print(render_table(
            ["ID", _t("col.name"), _t("col.size"),
             _t("col.modified"), "note"],
            table_rows,
            ["right", "left", "right", "left", "left"],
        ))

    def do_trash(self, arg: str) -> None:
        """trash [--json] — list items in the trash."""
        flags, _ = self._split_flags(self._args(arg))
        rows = self.engine.conflict_resolver.list_trash()
        if "json" in flags:
            self._print_json(rows)
            return
        if not rows:
            print("  " + Style.dim(_t("empty.trash")))
            return
        table_rows = []
        for r in rows:
            table_rows.append([
                str(r["id"]),
                os.path.basename(r.get("original_path", "")),
                human_size(r.get("size", 0)),
                time.strftime("%Y-%m-%d %H:%M",
                              time.localtime(r.get("deleted_at", 0))),
                r.get("reason", "") or "",
            ])
        print(render_table(
            ["ID", _t("col.name"), _t("col.size"),
             _t("col.modified"), "reason"],
            table_rows,
            ["right", "left", "right", "left", "left"],
        ))

    def do_settings(self, arg: str) -> None:
        """settings [--json] — show current configuration values."""
        flags, _ = self._split_flags(self._args(arg))
        data = self.config.public_dict()
        if "json" in flags:
            self._print_json(data)
            return
        print(section(_t("topbar.settings.title"), _t("topbar.settings.sub")))
        keys = sorted(k for k in data.keys())
        for k in keys:
            v = data[k]
            if isinstance(v, bool):
                v = Style.badge("on" if v else "off",
                                "success" if v else "danger")
            elif v is None:
                v = Style.dim("—")
            else:
                v = str(v)
            print(f"  {Style.dim(k.ljust(28))}  {v}")

    # ==================================================================
    # Actions — mirror the UI buttons
    # ==================================================================

    def do_upload(self, arg: str) -> None:
        """upload LOCAL [SHARE] [FOLDER] — copy a local file into a share."""
        flags, positional = self._split_flags(self._args(arg))
        if not positional:
            print(_t("err.usage", usage="upload LOCAL [SHARE] [FOLDER]"))
            return
        src = os.path.abspath(os.path.expanduser(positional[0]))
        if not os.path.isfile(src):
            print(Style.c(_t("err.missing", what=src), "bright_red"))
            return
        share = positional[1] if len(positional) > 1 else "received"
        folder = positional[2].strip("/") if len(positional) > 2 else ""

        shares = self.config.shares()
        if share not in shares:
            print(Style.c(_t("err.missing", what=share), "bright_red"))
            return

        from .utils import safe_join, unique_path  # local import for clarity
        root = shares[share]
        try:
            rel = (folder + "/" if folder else "") + os.path.basename(src)
            dest = safe_join(root, rel)
        except Exception as exc:
            print(Style.c(f"error: {exc}", "bright_red"))
            return

        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest):
            dest = unique_path(dest)
        shutil.copy2(src, dest)
        loc = self.engine.locate(dest)
        if loc:
            self.engine.index_path(*loc)
            self.engine._schedule_notify(loc[0])

        rel_out = os.path.relpath(dest, root).replace(os.sep, "/")
        print("  " + Style.c(_t("files.uploaded", share=share, path=rel_out),
                             "bright_green"))

    def do_rm(self, arg: str) -> None:
        """rm SHARE PATH [--permanent] — move a file to trash (or delete)."""
        flags, positional = self._split_flags(self._args(arg))
        if len(positional) < 2:
            print(_t("err.usage", usage="rm SHARE PATH [--permanent]"))
            return
        share, path = positional[0], positional[1]

        shares = self.config.shares()
        if share not in shares:
            print(Style.c(_t("err.missing", what=share), "bright_red"))
            return

        from .utils import safe_join
        try:
            full = safe_join(shares[share], path)
        except Exception as exc:
            print(Style.c(f"error: {exc}", "bright_red"))
            return
        if not os.path.exists(full):
            print(Style.c(_t("err.missing", what=path), "bright_red"))
            return

        permanent = bool(flags.get("permanent") or flags.get("P"))
        if permanent and not self._confirm(
                Style.c("Permanently delete? [y/N] ", "bright_red")):
            return

        if permanent:
            if os.path.isdir(full):
                shutil.rmtree(full)
            else:
                os.remove(full)
            msg = _t("files.permanent", path=path)
        else:
            self.engine.conflict_resolver.move_to_trash(full, "cli_delete")
            msg = _t("files.removed", path=path)

        self.engine.index_path(share, path)
        self.engine._schedule_notify(share)
        print("  " + Style.c(msg, "bright_green"))

    def do_download(self, arg: str) -> None:
        """download SHARE PATH [DEST] — copy a share file to a local path."""
        flags, positional = self._split_flags(self._args(arg))
        if len(positional) < 2:
            print(_t("err.usage", usage="download SHARE PATH [DEST]"))
            return
        share, path = positional[0], positional[1]
        dest = os.path.expanduser(positional[2]) if len(positional) > 2 \
            else os.path.join(os.getcwd(), os.path.basename(path))
        shares = self.config.shares()
        if share not in shares:
            print(Style.c(_t("err.missing", what=share), "bright_red"))
            return
        from .utils import safe_join
        try:
            src = safe_join(shares[share], path)
        except Exception as exc:
            print(Style.c(f"error: {exc}", "bright_red"))
            return
        if not os.path.isfile(src):
            print(Style.c(_t("err.missing", what=path), "bright_red"))
            return

        parent = os.path.dirname(dest)
        if parent:
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError as exc:
                print(Style.c(f"error: {exc}", "bright_red"))
                return
        try:
            shutil.copy2(src, dest)
        except OSError as exc:
            print(Style.c(f"error: {exc}", "bright_red"))
            return
        print("  " + Style.c(_t("files.downloaded", path=dest), "bright_green"))

    def do_resolve(self, arg: str) -> None:
        """resolve CONFLICT_ID accept|swap — resolve a stored conflict."""
        args = self._args(arg)
        if len(args) != 2 or args[1] not in ("accept", "swap"):
            print(_t("err.usage", usage="resolve CONFLICT_ID accept|swap"))
            return
        cid, action = args
        cr = self.engine.conflict_resolver
        row = cr.db.one("SELECT share FROM conflicts WHERE id=?", (cid,))
        if not row:
            print(Style.c(_t("conflict.not_found", cid=cid), "bright_red"))
            return
        ok, err = cr.resolve_manual(cid, action,
                                    self.config.shares()[row["share"]])
        if not ok:
            print(Style.c(str(err), "bright_red"))
            return
        print("  " + Style.c(_t("conflict.resolved", cid=cid[:8],
                                action=action), "bright_green"))

    def do_restore_version(self, arg: str) -> None:
        """restore-version VERSION_ID — restore a stored version."""
        args = self._args(arg)
        if len(args) != 1:
            print(_t("err.usage", usage="restore-version VERSION_ID"))
            return
        try:
            vid = int(args[0])
        except ValueError:
            print(Style.c(_t("err.usage", usage="restore-version VERSION_ID"),
                          "bright_yellow"))
            return
        if not self.engine.conflict_resolver.restore_version(vid):
            print(Style.c(_t("err.missing", what=vid), "bright_red"))
            return
        print("  " + Style.c(_t("version.restored", vid=vid), "bright_green"))

    def do_restore_trash(self, arg: str) -> None:
        """restore-trash TRASH_ID — restore an item from the trash."""
        args = self._args(arg)
        if len(args) != 1:
            print(_t("err.usage", usage="restore-trash TRASH_ID"))
            return
        try:
            tid = int(args[0])
        except ValueError:
            print(Style.c(_t("err.usage", usage="restore-trash TRASH_ID"),
                          "bright_yellow"))
            return
        row = self.engine.conflict_resolver.db.one(
            "SELECT original_path FROM trash WHERE id=?", (tid,))
        if not self.engine.conflict_resolver.restore_from_trash(tid):
            print(Style.c(_t("err.missing", what=tid), "bright_red"))
            return
        print("  " + Style.c(
            _t("trash.restored", path=(row or {}).get("original_path", "")),
            "bright_green"))

    def do_empty_trash(self, arg: str) -> None:
        """empty-trash [--days N] — permanently delete trashed items."""
        flags, _ = self._split_flags(self._args(arg))
        days = None
        if "days" in flags:
            try:
                days = int(flags["days"])
            except (TypeError, ValueError):
                print(Style.c(_t("err.usage", usage="empty-trash [--days N]"),
                              "bright_yellow"))
                return
        if not self._confirm():
            return
        n = self.engine.conflict_resolver.empty_trash(days)
        print("  " + Style.c(_t("trash.emptied", n=n), "bright_green"))

    def do_addpeer(self, arg: str) -> None:
        """addpeer HOST:PORT — register a peer manually."""
        args = self._args(arg)
        if len(args) != 1:
            print(_t("err.usage", usage="addpeer HOST:PORT"))
            return
        ok, info = self.engine.p2p_protocol.add_manual_peer(args[0])
        if ok:
            print("  " + Style.c(_t("peer.added", pid=info), "bright_green"))
        else:
            print("  " + Style.c(str(info), "bright_red"))

    def do_rmpeer(self, arg: str) -> None:
        """rmpeer PEER_ID — remove a peer from the registry."""
        args = self._args(arg)
        if len(args) != 1:
            print(_t("err.usage", usage="rmpeer PEER_ID"))
            return
        if not self.engine.p2p_protocol.remove_peer(args[0]):
            print(Style.c(_t("peer.not_found", pid=args[0]), "bright_red"))
            return
        print("  " + Style.c(_t("peer.removed", pid=args[0]), "bright_green"))

    def do_sync(self, arg: str) -> None:
        """sync [SHARE] [PEER_ID] — trigger a sync cycle."""
        args = self._args(arg)
        if not self.engine.running:
            print(Style.c(_t("sync.stopped_engine"), "bright_yellow"))
            return
        if not args:
            self.engine.sync_now()
            print("  " + Style.c(_t("sync.all"), "bright_green"))
            return
        share = args[0]
        if share not in self.config.shares():
            print(Style.c(_t("err.missing", what=share), "bright_red"))
            return
        if len(args) > 1:
            self.engine.request_sync(share, args[1])
        else:
            for peer in self.engine.p2p_protocol.online_peers():
                self.engine.request_sync(share, peer["id"])
        print("  " + Style.c(_t("sync.triggered", share=share), "bright_green"))

    def do_start(self, arg: str) -> None:
        """start — start the sync engine."""
        if self.engine.running:
            print("  " + Style.dim(_t("engine.already",
                                      state=_t("status.running"))))
            return
        self.engine.start()
        print("  " + Style.c(_t("engine.started"), "bright_green"))

    def do_stop(self, arg: str) -> None:
        """stop — stop the sync engine."""
        if not self.engine.running:
            print("  " + Style.dim(_t("engine.already",
                                      state=_t("status.stopped"))))
            return
        self.engine.stop()
        print("  " + Style.c(_t("engine.stopped"), "bright_yellow"))

    def do_addfolder(self, arg: str) -> None:
        """addfolder PATH — add a folder to the sync set."""
        args = self._args(arg)
        if len(args) != 1:
            print(_t("err.usage", usage="addfolder PATH"))
            return
        ok, err = self.engine.add_sync_folder(args[0])
        if not ok:
            print("  " + Style.c(str(err), "bright_red"))
            return
        print("  " + Style.c(_t("folder.added", path=args[0]), "bright_green"))

    def do_rmfolder(self, arg: str) -> None:
        """rmfolder PATH — stop syncing a folder (files are preserved)."""
        args = self._args(arg)
        if len(args) != 1:
            print(_t("err.usage", usage="rmfolder PATH"))
            return
        if not self.engine.remove_sync_folder(args[0]):
            print("  " + Style.c(_t("folder.not_found", path=args[0]),
                                 "bright_red"))
            return
        print("  " + Style.c(_t("folder.removed", path=args[0]),
                             "bright_yellow"))

    def do_folders(self, arg: str) -> None:
        """folders — list sync folders (shares)."""
        shares = self.config.shares()
        if not shares:
            print("  " + Style.dim(_t("empty.files")))
            return
        for sid, path in shares.items():
            marker = "★" if sid == "received" else " "
            print(f"  {Style.c(marker, 'bright_yellow')} "
                  f"{Style.c(sid.ljust(18), 'bright_blue')}  "
                  f"{Style.dim(path)}")

    # ==================================================================
    # Meta — language, watch, escape hatch
    # ==================================================================

    def do_lang(self, arg: str) -> None:
        """lang [ar|en|zh|hi|es] — switch the CLI language."""
        args = self._args(arg)
        if not args:
            langs = ", ".join(i18n.SUPPORTED_LANGS)
            print("  " + _t("lang.available", langs=langs))
            return
        code = args[0].strip().lower()
        if code not in i18n.SUPPORTED_LANGS:
            print(Style.c(f"unknown: {code}", "bright_red"))
            return
        i18n.set_language(code)
        print("  " + Style.c(_t("lang.set", lang=code), "bright_green"))

    def complete_lang(self, text: str, line: str,
                      begidx: int, endidx: int) -> list[str]:
        return [c for c in i18n.SUPPORTED_LANGS if c.startswith(text)]

    def do_watch(self, arg: str) -> None:
        """watch [SECONDS] [COMMAND] — re-run a command on an interval."""
        args = self._args(arg)
        interval = 3.0
        cmd_line = "status"
        if args:
            try:
                interval = max(0.5, float(args[0]))
                cmd_line = " ".join(args[1:]) or "status"
            except ValueError:
                cmd_line = " ".join(args)

        print("  " + Style.dim(_t("watch.started", interval=f"{interval:g}")))
        try:
            while True:
                clear_screen()
                print("  " + Style.dim(
                    time.strftime("%Y-%m-%d %H:%M:%S") + f"  ·  {cmd_line}"))
                self.onecmd(cmd_line)
                for _ in range(int(interval * 10)):
                    time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            print("  " + Style.dim(_t("watch.stopped")))

    def do_open(self, arg: str) -> None:
        """open — open the web UI in the default browser."""
        scheme = "https" if getattr(self.config, "_tls_active", False) else "http"
        port = self.config.active_port or self.config.server_port
        url = f"{scheme}://localhost:{port}"
        print("  " + _t("open.launched", url=Style.c(url, "bright_blue")))
        with contextlib.suppress(Exception):
            webbrowser.open(url)

    def do_shell(self, arg: str) -> None:
        """shell [CMD]  (or prefix a line with '!') — run a system command."""
        if not arg:
            print("  " + Style.dim(_t("shell.hint")))
            return
        try:
            subprocess.call(arg, shell=True)
        except (OSError, subprocess.SubprocessError) as exc:
            print(Style.c(str(exc), "bright_red"))
        print("  " + Style.dim(_t("shell.returned")))

    def do_clear(self, arg: str) -> None:
        """clear — clear the terminal screen."""
        clear_screen()

    # ==================================================================
    # Help system
    # ==================================================================

    _GROUPS: list[tuple[str, list[str]]] = [
        ("help.groups", ["status", "files", "shares", "peers", "conflicts",
                         "versions", "trash", "settings"]),
        ("help.actions", ["upload", "download", "rm", "resolve",
                          "restore_version", "restore_trash", "empty_trash",
                          "addpeer", "rmpeer", "addfolder", "rmfolder"]),
        ("help.control", ["start", "stop", "sync"]),
        ("help.meta", ["lang", "watch", "open", "shell", "clear",
                       "help", "quit"]),
    ]

    def do_help(self, arg: str) -> None:
        """help [COMMAND] — show the command reference or detailed help."""
        if arg:
            name = arg.strip().replace("-", "_")
            doc = getattr(self, f"do_{name}", None)
            if doc is None:
                print(Style.c(_t("err.unknown", cmd=arg), "bright_yellow"))
                return
            doc_text = (doc.__doc__ or "").strip()
            print(section(f"help {arg}"))
            print("  " + Style.bold(arg))
            if doc_text:
                for line in doc_text.splitlines():
                    print("    " + Style.dim(line.strip()))
            return

        print(section(_t("help.title")))
        for group_key, commands in self._GROUPS:
            print()
            print("  " + Style.bold(_t(group_key)))
            for cmd_name in commands:
                fn = getattr(self, f"do_{cmd_name}", None)
                if fn is None:
                    continue
                summary = (fn.__doc__ or "").splitlines()[0]
                print(f"    {Style.c(cmd_name.ljust(18), 'bright_blue')} "
                      f"{Style.dim(summary)}")
        print()
        print("  " + Style.dim(_t("hint.json")))
        print("  " + Style.dim("Keyboard: Tab autocompletes · Ctrl-C aborts · "
                               "Ctrl-D exits"))

    # ==================================================================
    # Tab completion — files, peers, shares, commands
    # ==================================================================

    def _complete_shares(self, text: str) -> list[str]:
        return [s for s in self.config.shares() if s.startswith(text)]

    def complete_files(self, text, line, begidx, endidx):
        """Complete ``files [SHARE] [FOLDER]``.

        Position 1 → share names.  Position 2 → folder entries inside the
        given share (mirrors ``do_files``'s folder argument).
        """
        args = self._args(line)
        if len(args) <= 2:
            return self._complete_shares(text)
        if len(args) == 3:
            share = args[1]
            if share in self.config.shares():
                return self._share_paths(share, text)
        return []

    def complete_upload(self, text, line, begidx, endidx):
        args = self._args(line)
        if len(args) <= 2:
            return [p for p in self._path_complete(text)]
        return self._complete_shares(text)

    def complete_download(self, text, line, begidx, endidx):
        args = self._args(line)
        if len(args) <= 2:
            return self._complete_shares(text)
        return self._path_complete(text)

    def complete_rm(self, text, line, begidx, endidx):
        args = self._args(line)
        if len(args) <= 2:
            return self._complete_shares(text)
        if len(args) == 3:
            share = args[1]
            if share in self.config.shares():
                return self._share_paths(share, text)
        return []

    def complete_addfolder(self, text, line, begidx, endidx):
        return self._path_complete(text)

    def complete_rmfolder(self, text, line, begidx, endidx):
        return [f for f in self.config.sync_folders if f.startswith(text)]

    def complete_rmpeer(self, text, line, begidx, endidx):
        return [p["id"] for p in self.engine.p2p_protocol.all_peers()
                if p["id"].startswith(text)]

    # [FIX-MIN-13] ``complete_versions`` أُزيل: كان يُعيد ``[]`` دائماً،
    # أي أنّه لا يُوفّر أي إكمال فعلي.  الآن يستخدم cmd.Cmd الإكمال
    # الافتراضي (أسماء الملفات) للوسيطة PATH، وهو أنفع.

    def _path_complete(self, text: str) -> list[str]:
        text = os.path.expanduser(text or ".")
        dirname = os.path.dirname(text) or "."
        prefix = os.path.basename(text)
        try:
            entries = os.listdir(dirname)
        except OSError:
            return []
        out = []
        for name in entries:
            if name.startswith(prefix):
                full = os.path.join(dirname, name)
                if os.path.isdir(full):
                    name += "/"
                out.append(name)
        return out

    def _share_paths(self, share: str, prefix: str) -> list[str]:
        root = self.config.shares().get(share)
        if not root:
            return []
        try:
            return [p for p in os.listdir(root) if p.startswith(prefix)]
        except OSError:
            return []

    # ==================================================================
    # Exit / formatting helpers
    # ==================================================================

    def do_quit(self, arg: str) -> bool:
        """quit — leave the CLI (the server keeps running in 'all' mode)."""
        print("  " + Style.dim("bye."))
        return True

    do_exit = do_quit
    do_EOF = do_quit

    @staticmethod
    def _human_duration(seconds: float) -> str:
        seconds = int(max(0, seconds))
        units = [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]
        parts = []
        for suffix, size in units:
            if seconds >= size:
                v, seconds = divmod(seconds, size)
                parts.append(f"{v}{suffix}")
            if len(parts) == 2:
                break
        return " ".join(parts) or "0s"