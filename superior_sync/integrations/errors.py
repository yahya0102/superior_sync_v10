"""Superior Sync integration subsystem."""

from __future__ import annotations

from ._shared import *


class ErrorLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    @property
    def weight(self) -> int:
        return {"debug": 10, "info": 20, "warning": 30,
                "error": 40, "critical": 50}[self.value]


class ErrorCategory(str, Enum):
    NETWORK = "network"
    AUTH = "auth"
    STORAGE = "storage"
    FILESYSTEM = "filesystem"
    CONFIG = "config"
    CLOUD = "cloud"
    SYNC = "sync"
    ENCRYPTION = "encryption"
    DATABASE = "database"
    VALIDATION = "validation"
    NOTIFICATION = "notification"
    ANALYTICS = "analytics"
    AUTOSTART = "autostart"
    UNKNOWN = "unknown"


_SUGGESTIONS: dict[str, list[tuple[str, str]]] = {
    ErrorCategory.NETWORK.value: [
        ("timed out", "تحقّق من اتصال الشبكة، أو ارفع المهلة في الإعدادات."),
        ("connection refused", "تأكّد أن الخدمة الهدف مشتغلة وأن المنفذ صحيح."),
        ("name or service not known", "تحقّق من اسم المضيف أو إعدادات DNS."),
        ("certificate", "شهادة TLS غير صالحة — حدّث الشهادة أو عطّل التحقّق."),
        ("ssl", "خطأ في طبقة TLS — تحقّق من السلسلة والشهادة."),
        ("reset by peer", "النظير أغلق الاتصال — قد يكون مشغولاً أو محجوباً."),
        ("unreachable", "المسار إلى الهدف غير متاح — تحقّق من التوجيه."),
    ],
    ErrorCategory.AUTH.value: [
        ("401", "بيانات الدخول غير صحيحة أو الرمز منتهي."),
        ("403", "لا تملك صلاحية لهذا الإجراء — راجع دور المستخدم."),
        ("signature", "توقيع الطلب غير مطابق — تأكّد من تطابق مفتاح المجموعة."),
        ("expired", "انتهت صلاحية الجلسة — أعد تسجيل الدخول."),
        ("locked", "الحساب مقفل مؤقتاً بسبب محاولات فاشلة — انتظر ثم أعد المحاولة."),
    ],
    ErrorCategory.FILESYSTEM.value: [
        ("permission denied", "لا تملك صلاحية القراءة/الكتابة على المسار."),
        ("no space left", "مساحة القرص ممتلئة — فرّغ مساحة أو غيّر الوجهة."),
        ("not found", "الملف أو المجلد غير موجود — تحقّق من المسار."),
        ("read-only file system", "نظام الملفات للقراءة فقط — لن تتم أي كتابة."),
        ("too many open files", "تجاوزت حد الملفات المفتوحة — ارفع ulimit."),
        ("is a directory", "المسار المتوقع ملف لكنه مجلد."),
        ("path traversal", "المسار يحاول الخروج من الجذر المسموح — مرفوض."),
    ],
    ErrorCategory.CLOUD.value: [
        ("401", "الرمز السحابي غير صالح أو منتهي — أعد ربط الخدمة."),
        ("403", "الحساب السحابي لا يملك صلاحية الوصول لهذا المورد."),
        ("404", "المورد السحابي غير موجود — تحقّق من المسار."),
        ("429", "تجاوزت حدود الخدمة السحابية — سيتم إعادة المحاولة تدريجياً."),
        ("500", "خطأ داخلي من الخدمة السحابية — أعد المحاولة لاحقاً."),
        ("502", "بوابة الخدمة السحابية سيئة — عطل مؤقت."),
        ("503", "الخدمة السحابية غير متوفرة حالياً."),
        ("504", "انتهت مهلة البوابة السحابية."),
        ("quota", "الحصة السحابية منتهية — احذف ملفات أو ارفع الخطة."),
        ("insufficient", "مساحة السحابة غير كافية لاستقبال الملف."),
    ],
    ErrorCategory.SYNC.value: [
        ("conflict", "تعارض بين نسختين — الحل التلقائي حسب الاستراتيجية."),
        ("hash mismatch", "بصمة الملف لا تطابق المتوقع — أُعيد النقل."),
        ("locked", "المورد مقفل من عملية أخرى — سيعاد المحاولة."),
        ("peer unreachable", "النظير غير متاح — تحقّق من الاتصال."),
    ],
    ErrorCategory.ENCRYPTION.value: [
        ("invalidtoken", "المفتاح غير مطابق أو البيانات تالفة — أعد التعيين."),
        ("cryptography", "مكتبة cryptography غير مثبتة — pip install cryptography."),
        ("group key", "مفتاح المجموعة مفقود أو غير متطابق بين الأجهزة."),
    ],
    ErrorCategory.CONFIG.value: [
        ("port", "المنفذ خارج النطاق المسموح 1024–65535."),
        ("key_short", "مفتاح المجموعة يجب أن يكون 24 حرفاً على الأقل."),
        ("unsafe path", "المسار غير آمن — اختر مجلداً عادياً."),
        ("crypto required", "التشفير مطلوب لكن غير متاح — ثبّت cryptography."),
    ],
    ErrorCategory.AUTOSTART.value: [
        ("systemctl", "فشل systemd — تحقّق من user session أو الصلاحيات."),
        ("permission", "صلاحيات غير كافية لتثبيت الإقلاع التلقائي."),
    ],
}

_GENERIC_SUGGESTIONS = {
    ErrorLevel.CRITICAL: "راجع السياق والتتبّع الكامل — الحادث قد يعطّل جزءاً من النظام.",
    ErrorLevel.ERROR: "راجع التفاصيل وأعد المحاولة. إن تكرّر الخطأ، راجع الإعدادات.",
    ErrorLevel.WARNING: "تحذير — قد يؤثّر على الأداء أو سلوك المزامنة.",
    ErrorLevel.INFO: "معلومة تشغيلية.",
    ErrorLevel.DEBUG: "معلومة تطويرية — تُعرض في الوضع المطوّل فقط.",
}


def _suggest_for(category: str, level: ErrorLevel, message: str) -> str:
    text = (message or "").lower()
    for pattern, advice in _SUGGESTIONS.get(category, ()):
        if pattern in text:
            return advice
    return _GENERIC_SUGGESTIONS.get(level, _GENERIC_SUGGESTIONS[ErrorLevel.ERROR])


def _classify(exc: BaseException | None, hint: str | None = None) -> str:
    if hint and hint in {c.value for c in ErrorCategory}:
        return hint
    if exc is None:
        return ErrorCategory.UNKNOWN.value
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "ssl" in name or "ssl" in text or "certificate" in text:
        return ErrorCategory.NETWORK.value
    if isinstance(exc, (ConnectionError, TimeoutError, socket.timeout, OSError)):
        if "permission" in text or "read-only" in text or "no space" in text:
            return ErrorCategory.FILESYSTEM.value
        if any(k in text for k in ("refused", "timed out", "unreachable",
                                   "getaddrinfo", "name or service")):
            return ErrorCategory.NETWORK.value
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError, ValueError)):
        return ErrorCategory.VALIDATION.value
    if "crypt" in name or "fernet" in name or "invalidtoken" in name:
        return ErrorCategory.ENCRYPTION.value
    if isinstance(exc, CloudError):
        return ErrorCategory.CLOUD.value
    return ErrorCategory.UNKNOWN.value


def _source_of_exception(exc: BaseException) -> dict:
    tb = exc.__traceback__
    if tb is None:
        return {}
    frames = traceback.extract_tb(tb)
    last = frames[-1]
    return {
        "file": os.path.basename(last.filename),
        "function": last.name,
        "line": last.lineno,
        "code": (last.line or "").strip(),
    }


# ==================================================================
# سجل الأخطاء — JSONL دائم + استعلام + تنبيهات
# ==================================================================

class ErrorLog:
    """سجل أخطاء منظّم: يخزّن، يصنّف، يقترح حلاً، ويطلق تنبيهات."""

    MAX_ENTRIES = 10_000
    FILE = "errors.jsonl"
    PRUNE_EVERY = 200

    def __init__(self, data_dir, config=None):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / self.FILE
        self.config = config
        self.lock = threading.RLock()
        self._entries: collections.deque[dict] = collections.deque(
            maxlen=self._effective_limit()
        )
        self._listeners: list[Callable[[dict], None]] = []
        self._write_count = 0
        self._stats = self._new_stats()
        self._load()

    # --------------------------------------------------------------
    def _effective_limit(self) -> int:
        if self.config is not None:
            try:
                return max(500, int(getattr(self.config, "error_log_max_entries",
                                            self.MAX_ENTRIES)))
            except (TypeError, ValueError):
                pass
        return self.MAX_ENTRIES

    def _new_stats(self) -> dict:
        return {
            "total": 0,
            "unresolved": 0,
            "by_level": {lvl.value: 0 for lvl in ErrorLevel},
            "by_category": {cat.value: 0 for cat in ErrorCategory},
            "recent_5m": 0,
            "recent_1h": 0,
        }

    def _load(self) -> None:
        if not self.file.exists():
            return
        try:
            with open(self.file, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self._entries.append(entry)
                    self._bump_stats(entry)
        except OSError as exc:
            log.warning("تعذّرت قراءة سجل الأخطاء: %s", exc)

    def _bump_stats(self, entry: dict) -> None:
        self._stats["total"] += 1
        lvl = entry.get("level", ErrorLevel.ERROR.value)
        cat = entry.get("category", ErrorCategory.UNKNOWN.value)
        self._stats["by_level"][lvl] = self._stats["by_level"].get(lvl, 0) + 1
        self._stats["by_category"][cat] = self._stats["by_category"].get(cat, 0) + 1
        if not entry.get("resolved"):
            self._stats["unresolved"] += 1

    def _prune_file(self) -> None:
        try:
            if self.file.stat().st_size < 8 * 1024 * 1024:
                return
            tmp = self.file.with_suffix(".jsonl.tmp")
            kept = list(self._entries)[-self._effective_limit():]
            with open(tmp, "w", encoding="utf-8") as fh:
                for entry in kept:
                    fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            os.replace(tmp, self.file)
        except OSError as exc:
            log.debug("تعذّر تقليم سجل الأخطاء: %s", exc)

    def _append(self, entry: dict) -> None:
        with self.lock:
            self._entries.append(entry)
            self._bump_stats(entry)
            self._write_count += 1
            try:
                with open(self.file, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            except OSError as exc:
                log.debug("تعذّر كتابة سجل الأخطاء: %s", exc)
            if self._write_count % self.PRUNE_EVERY == 0:
                self._prune_file()

    # --------------------------------------------------------------
    def log(
        self,
        message: str,
        *,
        level: ErrorLevel | str = ErrorLevel.ERROR,
        category: ErrorCategory | str | None = None,
        exc: BaseException | None = None,
        context: dict | None = None,
        source: str = "",
        trace_id: str | None = None,
        suggestion: str | None = None,
    ) -> dict:
        if isinstance(level, ErrorLevel):
            level_value = level.value
        else:
            level_value = str(level)
            if level_value not in {l.value for l in ErrorLevel}:
                level_value = ErrorLevel.ERROR.value

        category_value = (
            category.value if isinstance(category, ErrorCategory)
            else (category or _classify(exc))
        )

        trace = traceback.format_exc() if exc is not None else ""
        err_type = type(exc).__name__ if exc is not None else ""
        err_msg = str(exc) if exc is not None else ""

        entry = {
            "id": uuid.uuid4().hex[:16],
            "ts": time.time(),
            "level": level_value,
            "category": category_value,
            "message": str(message),
            "exc_type": err_type,
            "exc_message": err_msg,
            "source": source or self._infer_source(),
            "context": self._sanitize_context(context or {}),
            "traceback": trace,
            "trace_id": trace_id or uuid.uuid4().hex[:12],
            "suggestion": suggestion or _suggest_for(
                category_value,
                ErrorLevel(level_value),
                f"{message} {err_type} {err_msg}",
            ),
            "resolved": False,
            "resolved_at": None,
            "resolved_note": "",
        }
        if exc is not None:
            entry["origin"] = _source_of_exception(exc)

        self._append(entry)
        self._emit(entry)
        return entry

    @staticmethod
    def _sanitize_context(ctx: dict) -> dict:
        redacted_keys = {
            "password", "passwd", "secret", "token", "authorization",
            "apikey", "api_key", "group_key", "credentials", "cookie",
            "session", "master_password", "private_key",
        }
        out: dict = {}
        for key, value in ctx.items():
            low = str(key).lower()
            if any(r in low for r in redacted_keys):
                out[key] = "***redacted***"
            elif isinstance(value, (str, int, float, bool, type(None))):
                out[key] = value
            elif isinstance(value, (list, tuple)):
                out[key] = [str(v)[:200] for v in value[:20]]
            elif isinstance(value, dict):
                out[key] = {k: str(v)[:200] for k, v in list(value.items())[:20]}
            else:
                out[key] = str(value)[:200]
        return out

    @staticmethod
    def _infer_source() -> str:
        stack = traceback.extract_stack()
        for frame in reversed(stack[:-2]):
            if "integrations.py" in frame.filename:
                continue
            return f"{os.path.basename(frame.filename)}:{frame.lineno}::{frame.name}"
        return "unknown"

    def _emit(self, entry: dict) -> None:
        for cb in list(self._listeners):
            try:
                cb(entry)
            except Exception as exc:
                log.debug("مستمع سجل الأخطاء فشل: %s", exc)

    # --------------------------------------------------------------
    def on_entry(self, callback: Callable[[dict], None]) -> None:
        if callable(callback) and callback not in self._listeners:
            self._listeners.append(callback)

    def off_entry(self, callback: Callable[[dict], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    # --------------------------------------------------------------
    def query(
        self,
        *,
        level: ErrorLevel | str | None = None,
        category: ErrorCategory | str | None = None,
        since: float | None = None,
        only_unresolved: bool = False,
        search: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        level_value = level.value if isinstance(level, ErrorLevel) else level
        category_value = category.value if isinstance(category, ErrorCategory) else category
        needle = (search or "").lower()
        out: list[dict] = []
        with self.lock:
            for entry in reversed(self._entries):
                if level_value and entry.get("level") != level_value:
                    continue
                if category_value and entry.get("category") != category_value:
                    continue
                if since is not None and entry.get("ts", 0) < since:
                    continue
                if only_unresolved and entry.get("resolved"):
                    continue
                if needle:
                    blob = " ".join(str(entry.get(k, "")) for k in
                                    ("message", "exc_message", "source", "category"))
                    if needle not in blob.lower():
                        continue
                out.append(entry)
                if len(out) >= max(1, min(limit, 2000)):
                    break
        return out

    def get(self, entry_id: str) -> dict | None:
        with self.lock:
            for entry in reversed(self._entries):
                if entry.get("id") == entry_id:
                    return entry
        return None

    def mark_resolved(self, entry_id: str, note: str = "") -> bool:
        with self.lock:
            for entry in self._entries:
                if entry.get("id") == entry_id and not entry.get("resolved"):
                    entry["resolved"] = True
                    entry["resolved_at"] = time.time()
                    entry["resolved_note"] = note
                    self._stats["unresolved"] = max(0, self._stats["unresolved"] - 1)
                    self._rewrite()
                    return True
        return False

    def clear(self, *, category: str | None = None, level: str | None = None) -> int:
        with self.lock:
            before = len(self._entries)
            kept = []
            for entry in self._entries:
                if category and entry.get("category") != category:
                    kept.append(entry)
                    continue
                if level and entry.get("level") != level:
                    kept.append(entry)
                    continue
                if category or level:
                    continue
                if entry.get("resolved"):
                    continue
                kept.append(entry)
            self._entries.clear()
            for entry in kept:
                self._entries.append(entry)
            self._stats = self._new_stats()
            for entry in self._entries:
                self._bump_stats(entry)
            self._rewrite()
            return before - len(self._entries)

    def _rewrite(self) -> None:
        try:
            tmp = self.file.with_suffix(".jsonl.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                for entry in self._entries:
                    fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            os.replace(tmp, self.file)
        except OSError as exc:
            log.debug("تعذّر إعادة كتابة سجل الأخطاء: %s", exc)

    def stats(self) -> dict:
        now = time.time()
        with self.lock:
            recent_5m = sum(1 for e in self._entries if now - e.get("ts", 0) <= 300)
            recent_1h = sum(1 for e in self._entries if now - e.get("ts", 0) <= 3600)
            data = json.loads(json.dumps(self._stats, default=str))
            data["recent_5m"] = recent_5m
            data["recent_1h"] = recent_1h
            data["entries_in_memory"] = len(self._entries)
            data["file_path"] = str(self.file)
        return data

    def export(self) -> str:
        with self.lock:
            return "\n".join(
                json.dumps(e, ensure_ascii=False, default=str) for e in self._entries
            )


# ==================================================================
# التحليلات — قياسات + درجة صحة + عتبات
# ==================================================================
