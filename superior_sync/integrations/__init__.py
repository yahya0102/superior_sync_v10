"""Compatibility exports for the integrations package."""

from .analytics import AnalyticsEngine
from .autostart import autostart_status, install_autostart, remove_autostart
from .cloud import (
    CloudError,
    CloudIntegration,
    DropboxProvider,
    FolderProvider,
    GoogleDriveProvider,
    OneDriveProvider,
    WebDAVProvider,
    _PinnedHTTPConnection,
    _PinnedHTTPSConnection,
    _http,
    _http_once,
    _resolve_and_pin,
)
from .errors import ErrorCategory, ErrorLevel, ErrorLog
from .hub import IntegrationHub
from .notifications import NotificationPriority, NotificationSystem

__all__ = [
    "AnalyticsEngine",
    "CloudError",
    "CloudIntegration",
    "DropboxProvider",
    "ErrorCategory",
    "ErrorLevel",
    "ErrorLog",
    "FolderProvider",
    "GoogleDriveProvider",
    "IntegrationHub",
    "NotificationPriority",
    "NotificationSystem",
    "OneDriveProvider",
    "WebDAVProvider",
    "autostart_status",
    "install_autostart",
    "remove_autostart",
]
