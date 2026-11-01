#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""أدوات مساعدة عامة + مراقبة الملفات."""
from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import ipaddress
import logging
import logging.handlers
import os
import queue
import re
import socket
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

MAX_HASH_SIZE_BYTES = 2 * 1024 ** 3

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False

try:
    from watchfiles import watch as _wf_watch
    HAS_WATCHFILES = True
except ImportError:
    _wf_watch = None
    HAS_WATCHFILES = False

try:
    from cryptography.fernet import Fernet, InvalidToken
    HAS_CRYPTO = True
except ImportError:
    Fernet = None
    InvalidToken = Exception
    HAS_CRYPTO = False

from . import APP_NAME, APP_VERSION  # noqa: E402  (single source of truth)

log = logging.getLogger("superior_sync")
CLI_NOTIFIER = None


# ------------------------------------------------------------------
# [FIX-MED-3] الامتدادات التنفيذية المحظورة — مصدر واحد للحقيقة.
#
# كانت هذه القائمة مكرّرة بالحرف في ``routers/files.py`` و
# ``routers/p2p.py``، مما يجعل تحديثها عرضة للنسيان في أحد الموضعين.
# الآن كلاهما يستورد من هنا.
# ------------------------------------------------------------------
FORBIDDEN_EXECUTABLE_EXT: frozenset[str] = frozenset({
    ".exe", ".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs", ".vbe",
    ".jse", ".wsf", ".wsh", ".jar", ".msi", ".dll", ".so", ".dylib",
    ".app", ".deb", ".rpm", ".lnk", ".reg", ".hta", ".cpl", ".msc",
    ".gadget",
})


class PathError(ValueError):
    """مسار غير آمن أو خارج النطاق المسموح."""


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024


def default_data_dir():
    env = os.environ.get("SUPERIOR_SYNC_HOME")
    return Path(env) if env else Path.home() / ".superior_sync"


def atomic_write_bytes(path, data, mode=None):
    path = str(path)
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            try:
                os.chmod(tmp, mode)
            except OSError:
                pass
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def atomic_write_json(path, obj, mode=None):
    import json
    atomic_write_bytes(
        path,
        json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8"),
        mode)


def read_json(path, default=None):
    import json
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        log.warning("تعذّرت قراءة %s: %s", path, e)
        return default


_WIN_RESERVED = {"con", "prn", "aux", "nul",
                 *(f"com{i}" for i in range(1, 10)),
                 *(f"lpt{i}" for i in range(1, 10))}


def sanitize_relpath(rel):
    if rel is None:
        raise PathError("مسار فارغ")
    rel = str(rel).replace("\\", "/")
    if "\x00" in rel:
        raise PathError("مسار غير صالح")
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        raise PathError("مسارات مطلقة غير مسموحة")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise PathError("مسار غير آمن")
    if (any(p.split(".")[0].lower() in _WIN_RESERVED for p in parts)
            and os.name == "nt"):
        raise PathError("اسم محجوز")
    return "/".join(parts)


def safe_join(base, rel):
    rel = sanitize_relpath(rel)
    base_real = os.path.realpath(base)
    full = os.path.realpath(os.path.join(base_real, *rel.split("/")))
    if full != base_real and not full.startswith(base_real + os.sep):
        raise PathError("محاولة الخروج من المجلد المسموح")
    return full


def file_hash(path, chunk=1 << 20, *, max_size=None):
    h = hashlib.blake2b(digest_size=32)
    if max_size is not None and os.path.getsize(path) > max_size:
        raise ValueError(f"file exceeds the {max_size}-byte hash limit")
    total = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            total += len(b)
            if max_size is not None and total > max_size:
                raise ValueError(f"file exceeds the {max_size}-byte hash limit")
            h.update(b)
    return h.hexdigest()


BUILTIN_IGNORES = [
    "*.tmp", "*.temp", "*.swp", "*.swpx", "*.swx", "~$*", ".~lock.*",
    "*.part", "*.crdownload", "Thumbs.db", ".DS_Store", "desktop.ini",
    ".git", ".svn", ".hg", ".vs", "node_modules", "$RECYCLE.BIN",
    "System Volume Information", ".sync-tmp-*",
    # [FIX] الملفات المؤقتة التي ينشئها المحرك تأخذ الشكل ``<name>.sync-tmp-<id>``
    # (لاحقة لا بادئة)، ولم يكن النمط ``.sync-tmp-*`` يطابقها فتظهر في الفهرس
    # وفي الـ manifest المرسل إلى النظراء أثناء النقل.
    "*.sync-tmp-*", ".tmp-*", ".p2p_tmp", "*.restore-*",
]


def is_ignored(rel_or_name, extra=()):
    patterns = list(BUILTIN_IGNORES) + list(extra or ())
    for part in str(rel_or_name).replace("\\", "/").split("/"):
        if not part:
            continue
        low = part.lower()
        for p in patterns:
            if fnmatch.fnmatchcase(low, p.lower()):
                return True
    return False


def safe_eq(a, b) -> bool:
    """مقارنة ثابتة الزمن لنصوص قد تحوي محارف غير ASCII.

    ``hmac.compare_digest`` على ``str`` يرمي TypeError إن احتوى أحدهما محارف غير
    ASCII (ترويسة HTTP خبيثة مثلًا) فيتحول الأمر إلى خطأ 500.
    """
    import hmac as _hmac
    return _hmac.compare_digest(str(a).encode("utf-8", "replace"),
                                str(b).encode("utf-8", "replace"))


def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{base}_{i}{ext}"):
        i += 1
    return f"{base}_{i}{ext}"


def get_local_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            ips.add(sock.getsockname()[0])
    except OSError:
        pass
    ips = {i for i in ips if not i.startswith("127.")}
    return sorted(ips) or ["127.0.0.1"]


def get_local_ip():
    return get_local_ips()[0]


def is_safe_external_url(url, allow_private=False):
    """تحقّق من أن الرابط خارجي آمن (http/https، ليس عنواناً داخلياً)."""
    try:
        p = urllib.parse.urlparse(url)
    except (ValueError, TypeError):
        return False, "رابط غير صالح"
    if p.scheme not in ("http", "https"):
        return False, "يُسمح بـ http/https فقط"
    host = p.hostname
    if not host:
        return False, "المضيف مفقود"
    try:
        ip = ipaddress.ip_address(host)
        if (not allow_private and (ip.is_private or ip.is_loopback
                                   or ip.is_link_local or ip.is_reserved
                                   or ip.is_multicast or ip.is_unspecified)):
            return False, "عنوان داخلي محظور"
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, p.port or 0,
                                       proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            return False, "تعذّر تحليل اسم المضيف"
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if (not allow_private and (ip.is_private or ip.is_loopback
                                       or ip.is_link_local or ip.is_reserved
                                       or ip.is_multicast or ip.is_unspecified)):
                return False, "المضيف يحلّ إلى عنوان داخلي محظور"
    return True, None


def setup_logging(data_dir, verbose=False):
    root = logging.getLogger("superior_sync")
    if root.handlers:
        return
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    try:
        logdir = Path(data_dir) / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            logdir / "sync.log", maxBytes=2_000_000,
            backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(threadName)s: %(message)s"))
        root.addHandler(fh)
    except OSError:
        pass


# ==================================================================
# FileWatcher — كما هو
# ==================================================================
class FileWatcher:
    """مراقبة الملفات (watchfiles أو Polling)."""

    def __init__(self, config, ignore_fn=None, debounce=0.6,
                 polling_interval=2.0):
        self.config = config
        self.ignore_fn = ignore_fn
        self.debounce = debounce
        self.polling_interval = polling_interval
        self.watched_paths = {}
        self.change_callbacks = []
        self.running = False
        self.backend = None
        self._lock = threading.RLock()
        self._events = queue.Queue()
        self._threads = []
        self._cycle = threading.Event()
        self._snapshots = {}
        self._dir_mtimes = {}

    def start(self):
        if self.running:
            return
        self.running = True
        self._cycle.clear()
        self.backend = "watchfiles" if HAS_WATCHFILES else "polling"
        targets = [self._dispatch_loop]
        targets.append(self._watchfiles_loop if HAS_WATCHFILES
                       else self._polling_loop)
        for target in targets:
            t = threading.Thread(target=target, daemon=True,
                                 name=f"watcher-{target.__name__}")
            t.start()
            self._threads.append(t)
        log.info("👁️ بدء مراقبة الملفات باستخدام: %s",
                 self.backend_name())

    def stop(self):
        self.running = False
        self._cycle.set()
        for t in self._threads:
            t.join(timeout=3)
        self._threads = []

    def backend_name(self):
        return {"watchfiles": "watchfiles (أصلي)",
                "polling": f"Polling ({self.polling_interval:g}s)"
                }.get(self.backend, "متوقف")

    def add_watch_path(self, path, recursive=True):
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            return False
        with self._lock:
            self.watched_paths[path] = {
                "recursive": bool(recursive), "added_at": time.time()}
            self._snapshots.pop(path, None)
            self._dir_mtimes.pop(path, None)
        self._cycle.set()
        return True

    def remove_watch_path(self, path):
        path = os.path.abspath(path)
        with self._lock:
            existed = self.watched_paths.pop(path, None) is not None
            self._snapshots.pop(path, None)
            self._dir_mtimes.pop(path, None)
        self._cycle.set()
        return existed

    def register_callback(self, cb):
        if callable(cb) and cb not in self.change_callbacks:
            self.change_callbacks.append(cb)

    def unregister_callback(self, cb):
        if cb in self.change_callbacks:
            self.change_callbacks.remove(cb)

    def _watchfiles_loop(self):
        names = {1: "created", 2: "modified", 3: "deleted"}
        while self.running:
            with self._lock:
                paths = list(self.watched_paths)
            if not paths:
                self._cycle.wait(0.5)
                self._cycle.clear()
                continue
            self._cycle.clear()
            try:
                for changes in _wf_watch(
                        *paths, stop_event=self._cycle,
                        debounce=400, rust_timeout=1000,
                        yield_on_timeout=False,
                        raise_interrupt=False):
                    for ctype, fpath in changes:
                        self._events.put({
                            "type": names.get(int(ctype), "modified"),
                            "path": fpath, "time": time.time()})
                    if not self.running:
                        break
            except Exception as e:
                log.warning("watchfiles فشل (%s) — الانتقال إلى Polling", e)
                self.backend = "polling"
                self._polling_loop()
                return

    def _scan(self, root, recursive):
        state = {}
        stack = [root]
        while stack:
            d = stack.pop()
            try:
                it = os.scandir(d)
            except OSError:
                continue
            with it:
                for e in it:
                    try:
                        if is_ignored(e.name,
                                      self.config.ignore_patterns):
                            continue
                        if e.is_dir(follow_symlinks=False):
                            if recursive:
                                stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            st = e.stat(follow_symlinks=False)
                            state[e.path] = (st.st_size,
                                             st.st_mtime_ns,
                                             st.st_ino)
                    except OSError:
                        continue
        return state

    def _polling_loop(self):
        while self.running:
            with self._lock:
                items = list(self.watched_paths.items())
            for root, opts in items:
                if not self.running:
                    return
                # [FIX] كان هنا اختصار يتخطى المسح إذا لم يتغيّر mtime المجلد
                # الجذر. لكن mtime المجلد لا يتغيّر عند تعديل محتوى ملف ولا عند
                # أي تغيير داخل مجلد فرعي، فكان وضع Polling لا يكتشف إلا إنشاء
                # ملفات مباشرة في الجذر. نمسح الآن في كل دورة.
                if not os.path.isdir(root):
                    continue
                cur = self._scan(root, opts["recursive"])
                prev = self._snapshots.get(root)
                self._snapshots[root] = cur
                if prev is None:
                    continue
                created = [p for p in cur if p not in prev]
                deleted = [p for p in prev if p not in cur]
                now = time.time()
                if self.config.detect_moves and created and deleted:
                    by_sig = {}
                    for p in deleted:
                        s = prev[p]
                        by_sig.setdefault((s[0], s[1]), []).append(p)
                    for p in list(created):
                        s = cur[p]
                        cand = by_sig.get((s[0], s[1]))
                        if cand:
                            src = cand.pop(0)
                            deleted.remove(src)
                            created.remove(p)
                            self._events.put({
                                "type": "moved", "path": p,
                                "src": src, "time": now})
                for p in created:
                    self._events.put({"type": "created",
                                      "path": p, "time": now})
                for p in deleted:
                    self._events.put({"type": "deleted",
                                      "path": p, "time": now})
                for p, s in cur.items():
                    if (p in prev
                            and (prev[p][0] != s[0]
                                 or prev[p][1] != s[1])):
                        self._events.put({"type": "modified",
                                          "path": p, "time": now})
            self._cycle.wait(self.polling_interval)
            self._cycle.clear()

    def _should_process(self, event):
        try:
            if self.ignore_fn and self.ignore_fn(event["path"]):
                return False
        except Exception as e:
            log.warning("ignore_fn فشل لـ %s: %s",
                        event.get("path"), e)
            return True
        return not is_ignored(os.path.basename(event["path"]),
                              self.config.ignore_patterns)

    def _dispatch_loop(self):
        pending = {}
        while self.running or pending:
            try:
                ev = self._events.get(timeout=0.2)
                prev = pending.get(ev["path"])
                if (prev and prev["type"] == "created"
                        and ev["type"] == "modified"):
                    ev = dict(prev, time=ev["time"])
                pending[ev["path"]] = dict(ev, _seen=time.time())
            except queue.Empty:
                pass
            now = time.time()
            for path in [p for p, e in pending.items()
                         if (now - e["_seen"] >= self.debounce
                             or not self.running)]:
                ev = pending.pop(path)
                ev.pop("_seen", None)
                if not self._should_process(ev):
                    continue
                for cb in list(self.change_callbacks):
                    try:
                        cb(ev)
                    except Exception as e:
                        log.error("خطأ في callback المراقبة: %s", e)
            if not self.running and self._events.empty():
                break