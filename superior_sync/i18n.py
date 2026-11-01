"""Internationalisation engine — Arabic, English, Mandarin, Hindi, Spanish."""
from __future__ import annotations

from contextvars import ContextVar
from typing import Iterable

DEFAULT_LANG = "ar"
SUPPORTED_LANGS = ("ar", "en", "zh", "hi", "es")

_LANG_ALIASES = {
    "ar": "ar", "en": "en", "zh": "zh", "hi": "hi", "es": "es",
    "zh-cn": "zh", "zh-hans": "zh", "zh-hant": "zh",
}

_current_lang: ContextVar[str] = ContextVar("ss_lang", default=DEFAULT_LANG)


_TRANSLATIONS: dict[str, dict[str, str]] = {
    "ar": {
        "app.name": "Superior Sync",
        "app.tagline": "مزامنة ملفات فائقة بين الأجهزة",
        # auth
        "auth.login_required": "يلزم تسجيل الدخول",
        "auth.forbidden": "صلاحيات غير كافية",
        "auth.invalid_credentials": "بيانات الدخول غير صحيحة أو الحساب محظور مؤقتاً",
        "auth.password_changed": "تم تغيير كلمة المرور",
        "auth.logged_out": "تم تسجيل الخروج",
        "auth.session_expired": "انتهت الجلسة، يرجى تسجيل الدخول مجدداً",
        # generic
        "error.not_found": "العنصر غير موجود",
        "error.invalid_input": "بيانات غير صالحة",
        "error.internal": "خطأ داخلي في الخادم",
        "error.rate_limit": "تجاوزت الحد المسموح، حاول لاحقاً",
        "error.path_unsafe": "مسار غير آمن",
        "error.file_too_large": "حجم الملف يتجاوز الحد المسموح",
        "error.extension_blocked": "امتداد الملف {ext} غير مسموح",
        # sync
        "sync.started": "بدأت المزامنة",
        "sync.stopped": "توقفت المزامنة",
        "sync.completed": "اكتملت المزامنة",
        "sync.conflict_detected": "تعارض في الملفات: {path}",
        "sync.folder_added": "أُضيف المجلد",
        "sync.folder_removed": "أُزيل المجلد",
        "sync.peer_unreachable": "النظير غير قابل للوصول",
        "sync.auth_failed": "فشل التوثيق — تأكد من تطابق مفتاح المجموعة",
        # files
        "file.uploaded": "تم رفع الملف: {name}",
        "file.deleted": "نُقل الملف إلى السلة",
        "file.upload_aborted": "انقطع الرفع",
        "file.download_ready": "الملف جاهز للتنزيل",
        # security / diagnostics
        "diag.encryption_on": "تشفير النقل P2P مفعّل",
        "diag.encryption_off": "تشفير النقل P2P معطّل — البيانات بين الأجهزة غير مشفّرة",
        "diag.tls_on": "TLS على الخادم مفعّل",
        "diag.tls_off": "TLS على الخادم معطّل — الجلسات تُرسل عبر HTTP عادي",
        "diag.db_ok": "قاعدة البيانات سليمة",
        "diag.disk_low": "مساحة القرص منخفضة: {free}",
        # cloud
        "cloud.connected": "تم الاتصال بـ {service}",
        "cloud.disconnected": "تم قطع الاتصال بـ {service}",
        "cloud.connect_failed": "فشل الاتصال بـ {service}: {err}",
        "cloud.unsupported": "خدمة غير مدعومة",
        # notifications
        "notif.conflict_title": "تعارض في الملفات",
        "notif.conflict_body": "{path}: {action}",
        "notif.file_received_title": "ملف مستلم",
        "notif.sync_title": "اكتملت المزامنة",
        "notif.health_title": "تحذير صحي",
        # config
        "config.saved": "تم حفظ الإعدادات",
        "config.restart_required": "أعد تشغيل الخادم ليسري مفعول تغيير المنفذ",
        "config.key_short": "مفتاح المجموعة يجب أن يكون {n} حرفاً على الأقل",
    },
    "en": {
        "app.name": "Superior Sync",
        "app.tagline": "Blazing-fast peer-to-peer file synchronisation",
        "auth.login_required": "Authentication required",
        "auth.forbidden": "Insufficient permissions",
        "auth.invalid_credentials": "Invalid credentials or account temporarily locked",
        "auth.password_changed": "Password updated",
        "auth.logged_out": "Signed out",
        "auth.session_expired": "Session expired, please sign in again",
        "error.not_found": "Resource not found",
        "error.invalid_input": "Invalid input",
        "error.internal": "Internal server error",
        "error.rate_limit": "Rate limit exceeded, try again later",
        "error.path_unsafe": "Unsafe path",
        "error.file_too_large": "File exceeds the maximum allowed size",
        "error.extension_blocked": "Extension {ext} is blocked",
        "sync.started": "Sync started",
        "sync.stopped": "Sync stopped",
        "sync.completed": "Sync completed",
        "sync.conflict_detected": "File conflict: {path}",
        "sync.folder_added": "Folder added",
        "sync.folder_removed": "Folder removed",
        "sync.peer_unreachable": "Peer unreachable",
        "sync.auth_failed": "Authentication failed — verify group key",
        "file.uploaded": "File uploaded: {name}",
        "file.deleted": "File moved to trash",
        "file.upload_aborted": "Upload interrupted",
        "file.download_ready": "Download ready",
        "diag.encryption_on": "P2P transport encryption enabled",
        "diag.encryption_off": "P2P transport encryption disabled — traffic is plaintext",
        "diag.tls_on": "Server TLS enabled",
        "diag.tls_off": "Server TLS disabled — sessions sent over plain HTTP",
        "diag.db_ok": "Database integrity OK",
        "diag.disk_low": "Low disk space: {free}",
        "cloud.connected": "Connected to {service}",
        "cloud.disconnected": "Disconnected from {service}",
        "cloud.connect_failed": "Failed to connect to {service}: {err}",
        "cloud.unsupported": "Unsupported service",
        "notif.conflict_title": "File conflicts",
        "notif.conflict_body": "{path}: {action}",
        "notif.file_received_title": "File received",
        "notif.sync_title": "Sync completed",
        "notif.health_title": "Health warning",
        "config.saved": "Settings saved",
        "config.restart_required": "Restart required to apply the new port",
        "config.key_short": "Group key must be at least {n} characters",
    },
    "zh": {
        "app.name": "Superior Sync",
        "app.tagline": "极速点对点文件同步",
        "auth.login_required": "需要登录",
        "auth.forbidden": "权限不足",
        "auth.invalid_credentials": "凭证无效或账户被临时锁定",
        "auth.password_changed": "密码已更新",
        "auth.logged_out": "已退出登录",
        "auth.session_expired": "会话已过期，请重新登录",
        "error.not_found": "资源不存在",
        "error.invalid_input": "输入无效",
        "error.internal": "服务器内部错误",
        "error.rate_limit": "超出速率限制，请稍后重试",
        "error.path_unsafe": "不安全的路径",
        "error.file_too_large": "文件超过允许的最大大小",
        "error.extension_blocked": "扩展名 {ext} 被禁止",
        "sync.started": "同步已启动",
        "sync.stopped": "同步已停止",
        "sync.completed": "同步完成",
        "sync.conflict_detected": "文件冲突：{path}",
        "sync.folder_added": "文件夹已添加",
        "sync.folder_removed": "文件夹已移除",
        "sync.peer_unreachable": "无法访问对等节点",
        "sync.auth_failed": "认证失败——请检查组密钥",
        "file.uploaded": "文件已上传：{name}",
        "file.deleted": "文件已移至回收站",
        "file.upload_aborted": "上传中断",
        "file.download_ready": "下载已就绪",
        "diag.encryption_on": "P2P 传输加密已启用",
        "diag.encryption_off": "P2P 传输加密已禁用——流量为明文",
        "diag.tls_on": "服务器 TLS 已启用",
        "diag.tls_off": "服务器 TLS 已禁用——会话通过明文 HTTP 发送",
        "diag.db_ok": "数据库完整性良好",
        "diag.disk_low": "磁盘空间不足：{free}",
        "cloud.connected": "已连接到 {service}",
        "cloud.disconnected": "已断开与 {service} 的连接",
        "cloud.connect_failed": "连接 {service} 失败：{err}",
        "cloud.unsupported": "不支持的服务",
        "notif.conflict_title": "文件冲突",
        "notif.conflict_body": "{path}: {action}",
        "notif.file_received_title": "已接收文件",
        "notif.sync_title": "同步完成",
        "notif.health_title": "健康警告",
        "config.saved": "设置已保存",
        "config.restart_required": "需要重启以应用新端口",
        "config.key_short": "组密钥长度至少为 {n} 个字符",
    },
    "hi": {
        "app.name": "Superior Sync",
        "app.tagline": "अत्यंत तेज़ पीयर-टू-पीयर फ़ाइल सिंक",
        "auth.login_required": "लॉगिन आवश्यक",
        "auth.forbidden": "अपर्याप्त अनुमतियाँ",
        "auth.invalid_credentials": "अमान्य क्रेडेंशियल या खाता अस्थायी रूप से लॉक",
        "auth.password_changed": "पासवर्ड अपडेट किया गया",
        "auth.logged_out": "साइन आउट हो गया",
        "auth.session_expired": "सत्र समाप्त, कृपया पुनः साइन इन करें",
        "error.not_found": "संसाधन नहीं मिला",
        "error.invalid_input": "अमान्य इनपुट",
        "error.internal": "आंतरिक सर्वर त्रुटि",
        "error.rate_limit": "दर सीमा पार, बाद में पुनः प्रयास करें",
        "error.path_unsafe": "असुरक्षित पथ",
        "error.file_too_large": "फ़ाइल अधिकतम अनुमत आकार से अधिक है",
        "error.extension_blocked": "एक्सटेंशन {ext} अवरुद्ध है",
        "sync.started": "सिंक शुरू हुआ",
        "sync.stopped": "सिंक रुका",
        "sync.completed": "सिंक पूर्ण",
        "sync.conflict_detected": "फ़ाइल टकराव: {path}",
        "sync.folder_added": "फ़ोल्डर जोड़ा गया",
        "sync.folder_removed": "फ़ोल्डर हटाया गया",
        "sync.peer_unreachable": "पीयर अगम्य",
        "sync.auth_failed": "प्रमाणीकरण विफल — समूह कुंजी जाँचें",
        "file.uploaded": "फ़ाइल अपलोड हुई: {name}",
        "file.deleted": "फ़ाइल ट्रैश में भेजी गई",
        "file.upload_aborted": "अपलोड बाधित",
        "file.download_ready": "डाउनलोड तैयार",
        "diag.encryption_on": "P2P ट्रांसपोर्ट एन्क्रिप्शन सक्रिय",
        "diag.encryption_off": "P2P ट्रांसपोर्ट एन्क्रिप्शन अक्षम — ट्रैफ़िक प्लेनटेक्स्ट है",
        "diag.tls_on": "सर्वर TLS सक्रिय",
        "diag.tls_off": "सर्वर TLS अक्षम — सत्र सामान्य HTTP पर भेजे जाते हैं",
        "diag.db_ok": "डेटाबेस अखंडता ठीक है",
        "diag.disk_low": "कम डिस्क स्थान: {free}",
        "cloud.connected": "{service} से कनेक्ट किया गया",
        "cloud.disconnected": "{service} से डिस्कनेक्ट किया गया",
        "cloud.connect_failed": "{service} से कनेक्ट करने में विफल: {err}",
        "cloud.unsupported": "असमर्थित सेवा",
        "notif.conflict_title": "फ़ाइल टकराव",
        "notif.conflict_body": "{path}: {action}",
        "notif.file_received_title": "फ़ाइल प्राप्त हुई",
        "notif.sync_title": "सिंक पूर्ण",
        "notif.health_title": "स्वास्थ्य चेतावनी",
        "config.saved": "सेटिंग्स सहेजी गईं",
        "config.restart_required": "नया पोर्ट लागू करने के लिए पुनः आरंभ करें",
        "config.key_short": "समूह कुंजी कम से कम {n} वर्णों की होनी चाहिए",
    },
    "es": {
        "app.name": "Superior Sync",
        "app.tagline": "Sincronización de archivos P2P ultrarrápida",
        "auth.login_required": "Autenticación requerida",
        "auth.forbidden": "Permisos insuficientes",
        "auth.invalid_credentials": "Credenciales inválidas o cuenta bloqueada temporalmente",
        "auth.password_changed": "Contraseña actualizada",
        "auth.logged_out": "Sesión cerrada",
        "auth.session_expired": "La sesión ha expirado, inicia sesión de nuevo",
        "error.not_found": "Recurso no encontrado",
        "error.invalid_input": "Entrada no válida",
        "error.internal": "Error interno del servidor",
        "error.rate_limit": "Límite de peticiones excedido, inténtalo más tarde",
        "error.path_unsafe": "Ruta insegura",
        "error.file_too_large": "El archivo supera el tamaño máximo permitido",
        "error.extension_blocked": "La extensión {ext} está bloqueada",
        "sync.started": "Sincronización iniciada",
        "sync.stopped": "Sincronización detenida",
        "sync.completed": "Sincronización completada",
        "sync.conflict_detected": "Conflicto de archivo: {path}",
        "sync.folder_added": "Carpeta añadida",
        "sync.folder_removed": "Carpeta eliminada",
        "sync.peer_unreachable": "Par inalcanzable",
        "sync.auth_failed": "Autenticación fallida — verifica la clave de grupo",
        "file.uploaded": "Archivo subido: {name}",
        "file.deleted": "Archivo movido a la papelera",
        "file.upload_aborted": "Subida interrumpida",
        "file.download_ready": "Descarga lista",
        "diag.encryption_on": "Cifrado de transporte P2P activado",
        "diag.encryption_off": "Cifrado de transporte P2P desactivado — el tráfico es texto plano",
        "diag.tls_on": "TLS del servidor activado",
        "diag.tls_off": "TLS del servidor desactivado — las sesiones viajan por HTTP",
        "diag.db_ok": "Integridad de la base de datos correcta",
        "diag.disk_low": "Poco espacio en disco: {free}",
        "cloud.connected": "Conectado a {service}",
        "cloud.disconnected": "Desconectado de {service}",
        "cloud.connect_failed": "Error al conectar con {service}: {err}",
        "cloud.unsupported": "Servicio no soportado",
        "notif.conflict_title": "Conflictos de archivos",
        "notif.conflict_body": "{path}: {action}",
        "notif.file_received_title": "Archivo recibido",
        "notif.sync_title": "Sincronización completada",
        "notif.health_title": "Advertencia de estado",
        "config.saved": "Ajustes guardados",
        "config.restart_required": "Reinicia el servidor para aplicar el nuevo puerto",
        "config.key_short": "La clave de grupo debe tener al menos {n} caracteres",
    },
}


# Messages that used to be hard-coded in Arabic inside logic/routers.
_EXTRA: dict[str, dict[str, str]] = {
    "ar": {
        "auth.rate_limit_exceeded": "تجاوزت الحد المسموح، حاول لاحقاً",
        "error.port_range": "المنفذ يجب أن يكون بين 1024 و65535",
        "error.interval_range": "فترة المزامنة بين 1 و3600 ثانية",
        "error.unknown_strategy": "استراتيجية تعارض غير معروفة",
        "error.crypto_required": "التشفير يتطلب: pip install cryptography",
        "error.invalid_value": "قيمة غير صالحة: {detail}",
        "error.out_of_range": "{name} يجب أن يكون بين {lo} و{hi}",
        "sync.format_hostport": "الصيغة المطلوبة host:port",
        "sync.peer_connect_failed": "تعذّر الاتصال: {err}",
        "sync.peer_unknown": "النظير غير معروف",
        "sync.file_not_in_shares": "الملف غير موجود ضمن المجلدات المزامَنة",
        "sync.peer_rejected": "رفض النظير: {status}",
        "sync.folder_missing": "المجلد غير موجود",
        "sync.folder_is_data_dir": "لا يمكن مزامنة مجلد بيانات التطبيق",
        "sync.folder_overlap": "المجلد متداخل مع مجلد مزامنة موجود ({path})",
        "sync.folder_exists": "المجلد مضاف بالفعل",
        "conflict.not_found": "التعارض غير موجود",
        "conflict.no_copy": "لا توجد نسخة تعارض محفوظة للتبديل",
        "conflict.copy_missing": "ملف نسخة التعارض غير موجود",
        "conflict.unknown_action": "إجراء غير معروف",
    },
    "en": {
        "auth.rate_limit_exceeded": "Rate limit exceeded, try again later",
        "error.port_range": "Port must be between 1024 and 65535",
        "error.interval_range": "Sync interval must be between 1 and 3600 seconds",
        "error.unknown_strategy": "Unknown conflict strategy",
        "error.crypto_required": "Encryption requires: pip install cryptography",
        "error.invalid_value": "Invalid value: {detail}",
        "error.out_of_range": "{name} must be between {lo} and {hi}",
        "sync.format_hostport": "Expected format: host:port",
        "sync.peer_connect_failed": "Connection failed: {err}",
        "sync.peer_unknown": "Unknown peer",
        "sync.file_not_in_shares": "File is not inside a synced folder",
        "sync.peer_rejected": "Peer rejected the request: {status}",
        "sync.folder_missing": "Folder does not exist",
        "sync.folder_is_data_dir": "The application data folder cannot be synced",
        "sync.folder_overlap": "Folder overlaps an existing sync folder ({path})",
        "sync.folder_exists": "Folder already added",
        "conflict.not_found": "Conflict not found",
        "conflict.no_copy": "No saved conflict copy to swap with",
        "conflict.copy_missing": "Conflict copy file is missing",
        "conflict.unknown_action": "Unknown action",
    },
    "es": {
        "auth.rate_limit_exceeded": "Límite de solicitudes superado, inténtalo más tarde",
        "error.port_range": "El puerto debe estar entre 1024 y 65535",
        "error.interval_range": "El intervalo de sincronización debe estar entre 1 y 3600 segundos",
        "error.unknown_strategy": "Estrategia de conflicto desconocida",
        "error.crypto_required": "El cifrado requiere: pip install cryptography",
        "error.invalid_value": "Valor no válido: {detail}",
        "error.out_of_range": "{name} debe estar entre {lo} y {hi}",
        "sync.format_hostport": "Formato esperado: host:puerto",
        "sync.peer_connect_failed": "Error de conexión: {err}",
        "sync.peer_unknown": "Par desconocido",
        "sync.file_not_in_shares": "El archivo no está en una carpeta sincronizada",
        "sync.peer_rejected": "El par rechazó la solicitud: {status}",
        "sync.folder_missing": "La carpeta no existe",
        "sync.folder_is_data_dir": "No se puede sincronizar la carpeta de datos de la aplicación",
        "sync.folder_overlap": "La carpeta se solapa con una carpeta sincronizada ({path})",
        "sync.folder_exists": "La carpeta ya está añadida",
        "conflict.not_found": "Conflicto no encontrado",
        "conflict.no_copy": "No hay copia de conflicto guardada para intercambiar",
        "conflict.copy_missing": "Falta el archivo de copia del conflicto",
        "conflict.unknown_action": "Acción desconocida",
    },
    "zh": {
        "auth.rate_limit_exceeded": "请求过于频繁，请稍后再试",
        "error.port_range": "端口必须介于 1024 和 65535 之间",
        "error.interval_range": "同步间隔必须介于 1 到 3600 秒之间",
        "error.unknown_strategy": "未知的冲突策略",
        "error.crypto_required": "加密需要安装：pip install cryptography",
        "error.invalid_value": "无效的值：{detail}",
        "error.out_of_range": "{name} 必须介于 {lo} 和 {hi} 之间",
        "sync.format_hostport": "格式应为 host:port",
        "sync.peer_connect_failed": "连接失败：{err}",
        "sync.peer_unknown": "未知的节点",
        "sync.file_not_in_shares": "文件不在已同步的文件夹中",
        "sync.peer_rejected": "节点拒绝了请求：{status}",
        "sync.folder_missing": "文件夹不存在",
        "sync.folder_is_data_dir": "无法同步应用程序的数据文件夹",
        "sync.folder_overlap": "该文件夹与现有同步文件夹重叠（{path}）",
        "sync.folder_exists": "文件夹已添加",
        "conflict.not_found": "未找到冲突",
        "conflict.no_copy": "没有可用于交换的冲突副本",
        "conflict.copy_missing": "冲突副本文件不存在",
        "conflict.unknown_action": "未知的操作",
    },
    "hi": {
        "auth.rate_limit_exceeded": "अनुरोध सीमा पार हो गई, बाद में पुनः प्रयास करें",
        "error.port_range": "पोर्ट 1024 और 65535 के बीच होना चाहिए",
        "error.interval_range": "सिंक अंतराल 1 से 3600 सेकंड के बीच होना चाहिए",
        "error.unknown_strategy": "अज्ञात टकराव रणनीति",
        "error.crypto_required": "एन्क्रिप्शन के लिए आवश्यक: pip install cryptography",
        "error.invalid_value": "अमान्य मान: {detail}",
        "error.out_of_range": "{name} {lo} और {hi} के बीच होना चाहिए",
        "sync.format_hostport": "अपेक्षित प्रारूप: host:port",
        "sync.peer_connect_failed": "कनेक्शन विफल: {err}",
        "sync.peer_unknown": "अज्ञात पीयर",
        "sync.file_not_in_shares": "फ़ाइल सिंक किए गए फ़ोल्डर में नहीं है",
        "sync.peer_rejected": "पीयर ने अनुरोध अस्वीकार किया: {status}",
        "sync.folder_missing": "फ़ोल्डर मौजूद नहीं है",
        "sync.folder_is_data_dir": "एप्लिकेशन का डेटा फ़ोल्डर सिंक नहीं किया जा सकता",
        "sync.folder_overlap": "फ़ोल्डर मौजूदा सिंक फ़ोल्डर से ओवरलैप करता है ({path})",
        "sync.folder_exists": "फ़ोल्डर पहले से जोड़ा गया है",
        "conflict.not_found": "टकराव नहीं मिला",
        "conflict.no_copy": "अदला-बदली के लिए कोई सहेजी गई टकराव प्रति नहीं है",
        "conflict.copy_missing": "टकराव प्रति फ़ाइल मौजूद नहीं है",
        "conflict.unknown_action": "अज्ञात क्रिया",
    },
}
for _lang, _extra in _EXTRA.items():
    _TRANSLATIONS[_lang].update(_extra)


def normalize_lang(raw: str | None) -> str:
    """Turn an Accept-Language header or ?lang= value into a supported code."""
    if not raw:
        return DEFAULT_LANG
    for part in raw.split(","):
        tag = part.split(";")[0].strip().lower()
        if not tag:
            continue
        if tag in _LANG_ALIASES:
            return _LANG_ALIASES[tag]
        primary = tag.split("-")[0]
        if primary in _LANG_ALIASES:
            return _LANG_ALIASES[primary]
    return DEFAULT_LANG


def set_language(lang: str) -> str:
    code = normalize_lang(lang)
    _current_lang.set(code)
    return code


def get_language() -> str:
    return _current_lang.get()


def t(key: str, /, **kwargs) -> str:
    """Translate `key` using the current context language."""
    lang = _current_lang.get()
    table: Iterable[str] = _TRANSLATIONS.get(lang) or _TRANSLATIONS[DEFAULT_LANG]
    text = table.get(key)
    if text is None:
        text = _TRANSLATIONS[DEFAULT_LANG].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def available_languages() -> list[dict[str, str]]:
    return [
        {"code": "ar", "label": "العربية",   "dir": "rtl"},
        {"code": "en", "label": "English",   "dir": "ltr"},
        {"code": "zh", "label": "中文",       "dir": "ltr"},
        {"code": "hi", "label": "हिन्दी",      "dir": "ltr"},
        {"code": "es", "label": "Español",   "dir": "ltr"},
    ]