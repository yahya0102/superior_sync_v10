"""Superior Sync integration subsystem."""

from __future__ import annotations

from ._shared import *
from .errors import ErrorCategory, ErrorLevel


class NotificationPriority(str, Enum):
    SILENT = "silent"
    NORMAL = "normal"
    URGENT = "urgent"


class NotificationSystem:
    MAX_KEPT = 500

    def __init__(self, data_dir, desktop=True, config=None, hub=None):
        self.file = Path(data_dir) / "notifications.json"
        self.config = config
        self.hub = hub
        self.lock = threading.RLock()
        self.notifications: list[dict] = read_json(self.file, []) or []
        self.platform = platform.system()
        self.desktop = desktop and self._desktop_enabled()
        self.callbacks: dict[str, list[Callable]] = {
            "on_notification": [],
            "on_click": [],
            "on_close": [],
        }

    def _desktop_enabled(self) -> bool:
        if self.config is None:
            return True
        return bool(getattr(self.config, "notifications_desktop_enabled", True))

    def _max_kept(self) -> int:
        if self.config is None:
            return self.MAX_KEPT
        try:
            return max(50, int(getattr(self.config, "notifications_max_entries",
                                       self.MAX_KEPT)))
        except (TypeError, ValueError):
            return self.MAX_KEPT

    @property
    def unread_count(self) -> int:
        return sum(1 for n in self.notifications if not n.get("read"))

    def _save(self) -> None:
        try:
            atomic_write_json(self.file, self.notifications[-self._max_kept():])
        except OSError as exc:
            log.debug("حفظ الإشعارات: %s", exc)

    def show_notification(
        self,
        title: str,
        message: str,
        notification_type: str = "info",
        *,
        actions: list[dict] | None = None,
        timeout: int = 10,
        priority: NotificationPriority | str = NotificationPriority.NORMAL,
        category: str = "general",
        dedupe_key: str | None = None,
        progress: float | None = None,
        event: str | None = None,
        data: dict | None = None,
    ) -> str:
        priority_value = priority.value if isinstance(priority, NotificationPriority) else str(priority)
        if priority_value not in {p.value for p in NotificationPriority}:
            priority_value = NotificationPriority.NORMAL.value

        if dedupe_key:
            for existing in reversed(self.notifications):
                if (existing.get("dedupe_key") == dedupe_key
                        and not existing.get("read")
                        and time.time() - existing.get("timestamp", 0) < 60):
                    existing["message"] = str(message)
                    existing["timestamp"] = time.time()
                    existing["progress"] = progress
                    self._save()
                    self._broadcast("notification_updated", existing)
                    return existing["id"]

        entry = {
            "id": uuid.uuid4().hex,
            "title": str(title)[:200],
            "message": str(message)[:2000],
            "type": notification_type,
            "priority": priority_value,
            "category": category,
            "timestamp": time.time(),
            "read": False,
            "actions": list(actions or []),
            "timeout": max(0, int(timeout)),
            "dedupe_key": dedupe_key,
            "progress": progress,
        }

        with self.lock:
            self.notifications.append(entry)
            self.notifications = self.notifications[-self._max_kept():]
            self._save()

        log.info("🔔 %s — %s", entry["title"], entry["message"])
        from . import utils as _u
        if _u.CLI_NOTIFIER and priority_value != NotificationPriority.SILENT.value:
            with contextlib.suppress(Exception):
                _u.CLI_NOTIFIER(f"🔔 {title}: {message}")

        if self.desktop and priority_value != NotificationPriority.SILENT.value:
            threading.Thread(target=self._desktop, args=(entry,), daemon=True).start()

        self._broadcast(event or "notification_created", entry)

        for cb in self.callbacks["on_notification"]:
            with contextlib.suppress(Exception):
                cb(entry)

        return entry["id"]

    def _broadcast(self, event: str, payload: dict) -> None:
        if self.hub is not None:
            self.hub.emit(event, payload)

    def _desktop(self, entry: dict) -> None:
        title, msg = entry["title"][:100], entry["message"][:250]
        timeout_ms = max(1000, int(entry.get("timeout", 10)) * 1000)
        try:
            if self.platform == "Linux" and shutil.which("notify-send"):
                urgency = {"silent": "low", "normal": "normal", "urgent": "critical"}.get(
                    entry.get("priority", "normal"), "normal"
                )
                subprocess.run(
                    ["notify-send", "-u", urgency, "-t", str(timeout_ms), "--", title, msg],
                    timeout=5, check=False,
                )
            elif self.platform == "Darwin" and shutil.which("osascript"):
                def esc(s):
                    return s.replace("\\", "\\\\").replace('"', '\\"')
                subprocess.run(
                    ["osascript", "-e",
                     f'display notification "{esc(msg)}" with title "{esc(title)}"'],
                    timeout=5, check=False,
                )
            elif self.platform == "Windows":
                ps = (
                    "Add-Type -AssemblyName System.Windows.Forms;"
                    "$n=New-Object System.Windows.Forms.NotifyIcon;"
                    "$n.Icon=[System.Drawing.SystemIcons]::Information;$n.Visible=$true;"
                    f"$n.ShowBalloonTip({timeout_ms},$env:SS_T,$env:SS_M,'Info');"
                    "Start-Sleep 6;$n.Dispose()"
                )
                env = dict(os.environ, SS_T=title, SS_M=msg)
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                    env=env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
        except (OSError, subprocess.SubprocessError):
            pass

    def mark_as_read(self, notification_id: str) -> bool:
        with self.lock:
            for entry in self.notifications:
                if entry["id"] == notification_id:
                    entry["read"] = True
                    self._save()
                    self._broadcast("notification_read", {"id": notification_id})
                    return True
        return False

    def mark_all_as_read(self) -> None:
        with self.lock:
            for entry in self.notifications:
                entry["read"] = True
            self._save()
        self._broadcast("notifications_all_read", {})

    def delete_notification(self, notification_id: str) -> bool:
        with self.lock:
            before = len(self.notifications)
            self.notifications = [n for n in self.notifications if n["id"] != notification_id]
            self._save()
        if len(self.notifications) != before:
            self._broadcast("notification_deleted", {"id": notification_id})
            return True
        return False

    def clear_all(self) -> None:
        with self.lock:
            self.notifications = []
            self._save()
        self._broadcast("notifications_cleared", {})

    def get_notifications(
        self,
        unread_only: bool = False,
        limit: int = 50,
        category: str | None = None,
        priority: str | None = None,
    ) -> list[dict]:
        with self.lock:
            rows = self.notifications
            if unread_only:
                rows = [n for n in rows if not n.get("read")]
            if category:
                rows = [n for n in rows if n.get("category") == category]
            if priority:
                rows = [n for n in rows if n.get("priority") == priority]
        return list(reversed(rows))[:max(1, min(limit, 500))]

    def register_callback(self, event: str, cb: Callable) -> None:
        self.callbacks.setdefault(event, []).append(cb)

    def unregister_callback(self, event: str, cb: Callable) -> None:
        if cb in self.callbacks.get(event, []):
            self.callbacks[event].remove(cb)


# ==================================================================
# طبقة HTTP آمنة ضد SSRF — مع إعادة محاولة وتتبّع تفصيلي
# ==================================================================
