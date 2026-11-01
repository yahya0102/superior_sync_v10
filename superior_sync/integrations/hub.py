"""Superior Sync integration subsystem."""

from __future__ import annotations

from ._shared import *
from .errors import ErrorCategory, ErrorLevel, ErrorLog
from .analytics import AnalyticsEngine
from .notifications import NotificationPriority, NotificationSystem
from .cloud import CloudIntegration
from .autostart import autostart_status


class IntegrationHub:
    """منسّق مركزي: سجل الأخطاء، الإشعارات، التحليلات، السحابة، التنبيهات."""

    def __init__(self, config, engine=None, *, desktop_notifications: bool = True):
        self.config = config
        self.engine = engine
        self.errors = ErrorLog(config.data_dir, config=config)
        self.notifier = NotificationSystem(
            config.data_dir,
            desktop=desktop_notifications,
            config=config, hub=self,
        )
        self.analytics = AnalyticsEngine(
            config.data_dir, engine=engine,
            interval=int(getattr(config, "analytics_interval", 5) or 5),
            config=config, hub=self,
        )
        self.cloud = CloudIntegration(
            config, error_log=self.errors, hub=self,
        )
        self._sse_broadcast: Callable[[str, dict], None] | None = None
        self._alert_cooldowns: dict[str, float] = {}
        self._alert_lock = threading.Lock()

        self.errors.on_entry(self._route_error)

    # --------------------------------------------------------------
    # التوصيل مع التطبيق
    # --------------------------------------------------------------

    def attach_broadcast(self, fn: Callable[[str, dict], None]) -> None:
        self._sse_broadcast = fn

    def emit(self, event: str, payload: dict) -> None:
        if self._sse_broadcast is not None:
            with contextlib.suppress(Exception):
                self._sse_broadcast(event, payload)

    # --------------------------------------------------------------
    # التقاط الأخطاء
    # --------------------------------------------------------------

    def report(
        self,
        exc: BaseException | None,
        message: str,
        *,
        level: ErrorLevel | str = ErrorLevel.ERROR,
        category: ErrorCategory | str | None = None,
        context: dict | None = None,
    ) -> dict:
        entry = self.errors.log(
            message, level=level, category=category, exc=exc, context=context,
        )
        return entry

    def _route_error(self, entry: dict) -> None:
        self.emit("error_logged", entry)
        level = entry.get("level")
        if level not in (ErrorLevel.ERROR.value, ErrorLevel.CRITICAL.value):
            return
        if entry.get("category") == ErrorCategory.ANALYTICS.value:
            return
        self.notifier.show_notification(
            f"خطأ في {entry.get('category', 'unknown')}",
            entry.get("message", ""),
            notification_type="error",
            priority=NotificationPriority.URGENT,
            category=entry.get("category", "error"),
            dedupe_key=f"err:{entry.get('category')}:{entry.get('exc_type')}",
            actions=[{"id": "open_errors", "label": "عرض السجل", "kind": "primary"}],
        )

    # --------------------------------------------------------------
    # التنبيهات والإشعارات
    # --------------------------------------------------------------

    def alert(
        self,
        title: str,
        message: str,
        *,
        level: ErrorLevel | str = ErrorLevel.WARNING,
        category: ErrorCategory | str = ErrorCategory.UNKNOWN,
        cooldown: float = 300,
        dedupe_key: str | None = None,
    ) -> dict:
        key = dedupe_key or f"{category}:{title}"
        now = time.time()
        with self._alert_lock:
            if now - self._alert_cooldowns.get(key, 0) < cooldown:
                return self.errors.get(key) or {"skipped": True, "reason": "cooldown"}
            self._alert_cooldowns[key] = now
        entry = self.errors.log(message, level=level, category=category,
                                context={"alert": True})
        self.notifier.show_notification(
            title, message,
            notification_type="warning" if level == ErrorLevel.WARNING else "error",
            priority=(NotificationPriority.URGENT
                      if level == ErrorLevel.CRITICAL else NotificationPriority.NORMAL),
            category=category.value if isinstance(category, ErrorCategory) else category,
            dedupe_key=key,
        )
        return entry

    def notify(self, title: str, message: str, **kwargs) -> str:
        return self.notifier.show_notification(title, message, **kwargs)

    # --------------------------------------------------------------
    # التشغيل والإيقاف
    # --------------------------------------------------------------

    def start(self) -> None:
        self.analytics.start()

    def stop(self) -> None:
        self.analytics.stop()

    # --------------------------------------------------------------
    # لقطة صحة موحّدة
    # --------------------------------------------------------------

    def health_snapshot(self) -> dict:
        analytics_health = self.analytics.health_score()
        err_stats = self.errors.stats()
        notif_unread = self.notifier.unread_count
        cloud_health = self.cloud.health()
        return {
            "score": analytics_health["score"],
            "grade": analytics_health["grade"],
            "factors": analytics_health["factors"],
            "system": analytics_health["snapshot"],
            "errors": {
                "total": err_stats["total"],
                "unresolved": err_stats["unresolved"],
                "recent_5m": err_stats["recent_5m"],
                "recent_1h": err_stats["recent_1h"],
                "by_category": err_stats["by_category"],
                "by_level": err_stats["by_level"],
            },
            "notifications": {"unread": notif_unread},
            "cloud": cloud_health,
            "autostart": autostart_status(),
            "timestamp": time.time(),
        }
