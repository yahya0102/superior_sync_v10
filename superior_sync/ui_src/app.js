"use strict";
const LOCAL_TOKEN = __SS_LOCAL_TOKEN_PLACEHOLDER__;
/* ============================================================
   TRANSLATIONS
   ============================================================ */
const I18N = {
  ar: {
    "app.tagline":"مزامنة ملفات نظير-لنظير",
    "nav.section.main":"التنقل",
    "nav.files":"الملفات",
    "nav.peers":"الأجهزة",
    "nav.conflicts":"التعارضات",
    "nav.status":"الحالة",
    "nav.settings":"الإعدادات",
    "topbar.files.title":"الملفات",
    "topbar.files.sub":"تصفح وحمّل وارفع الملفات",
    "topbar.peers.title":"الأجهزة",
    "topbar.peers.sub":"اكتشاف النظراء وإدارة الاتصالات",
    "topbar.conflicts.title":"التعارضات",
    "topbar.conflicts.sub":"حل التعارضات بين النسخ",
    "topbar.status.title":"الحالة",
    "topbar.status.sub":"مراقبة محرك المزامنة",
    "topbar.settings.title":"الإعدادات",
    "topbar.settings.sub":"ضبط سلوك المزامنة والأمان",
    "common.cancel":"إلغاء",
    "common.confirm":"تأكيد",
    "common.close":"إغلاق",
    "common.save":"حفظ",
    "common.delete":"حذف",
    "common.download":"تنزيل",
    "common.refresh":"تحديث",
    "common.search":"بحث",
    "common.loading":"جارٍ التحميل…",
    "common.of":"من",
    "common.actions":"إجراءات",
    "common.language":"اللغة",
    "common.theme":"المظهر",
    "common.darkMode":"داكن",
    "common.lightMode":"فاتح",
    "common.arabic":"العربية",
    "common.english":"English",
    "files.upload":"رفع ملفات",
    "files.searchPlaceholder":"ابحث في هذا المجلد…",
    "files.list":"قائمة",
    "files.grid":"شبكة",
    "files.empty":"هذا المجلد فارغ",
    "files.emptyHint":"اسحب الملفات هنا أو استخدم زر الرفع لإضافتها.",
    "files.emptySearch":"لا توجد نتائج مطابقة",
    "files.emptySearchHint":"جرّب مصطلح بحث مختلف.",
    "files.drop.title":"أفلت الملفات للرفع",
    "files.drop.hint":"سيتم رفعها إلى المجلد الحالي.",
    "files.col.name":"الاسم",
    "files.col.size":"الحجم",
    "files.col.modified":"آخر تعديل",
    "files.col.type":"النوع",
    "files.confirmDelete":"هل تريد نقل هذا العنصر إلى سلة المحذوفات؟",
    "files.uploading":"جارٍ رفع {name}…",
    "files.uploaded":"تم رفع {name}",
    "files.deleted":"تم نقل العنصر إلى السلة",
    "files.downloaded":"جارٍ التنزيل…",
    "files.breadcrumbRoot":"البداية",
    "peers.add":"إضافة جهاز",
    "peers.address":"العنوان (مضيف:منفذ)",
    "peers.addressPlaceholder":"192.168.1.10:8080",
    "peers.empty":"لا توجد أجهزة معروفة",
    "peers.emptyHint":"أضف جهازاً يدوياً أو انتظر الاكتشاف التلقائي عبر الشبكة المحلية.",
    "peers.status.online":"متصل",
    "peers.status.offline":"غير متصل",
    "peers.syncNow":"مزامنة",
    "peers.remove":"إزالة",
    "peers.confirmRemove":"إزالة هذا الجهاز من القائمة؟",
    "peers.added":"تمت إضافة الجهاز",
    "peers.removed":"تمت إزالة الجهاز",
    "peers.syncTriggered":"تم إرسال أمر المزامنة",
    "peers.lastSeen":"آخر ظهور",
    "peers.never":"—",
    "peers.invalidAddress":"استخدم الصيغة مضيف:منفذ",
    "conflicts.empty":"لا توجد تعارضات",
    "conflicts.emptyHint":"كل النسخ متزامنة تماماً. رائع!",
    "conflicts.detectedAt":"تاريخ الاكتشاف",
    "conflicts.accept":"قبول",
    "conflicts.swap":"تبديل",
    "conflicts.resolved":"تم حل التعارض",
    "status.start":"تشغيل",
    "status.stop":"إيقاف",
    "status.syncNow":"مزامنة الآن",
    "status.running":"يعمل",
    "status.stopped":"متوقف",
    "status.node":"الجهاز",
    "status.files":"الملفات المفهرسة",
    "status.sent":"المُرسل",
    "status.received":"المُستقبل",
    "status.conflicts":"التعارضات",
    "status.peersOnline":"نظراء متصلون",
    "status.errors":"آخر الأخطاء",
    "status.noErrors":"لا توجد أخطاء حديثة",
    "status.lastSync":"آخر مزامنة",
    "status.never":"لم تتم بعد",
    "status.engineOn":"بدأ المحرك",
    "status.engineOff":"توقف المحرك",
    "status.syncTriggered":"تم جدولة دورة مزامنة",
    "settings.nodeName":"اسم الجهاز",
    "settings.syncInterval":"فاصل المزامنة (ثانية)",
    "settings.conflictStrategy":"استراتيجية حل التعارض",
    "settings.strategy.newer":"الأحدث يفوز",
    "settings.strategy.older":"الأقدم يفوز",
    "settings.strategy.larger":"الأكبر يفوز",
    "settings.strategy.source":"المصدر يفوز",
    "settings.strategy.target":"الهدف يفوز",
    "settings.strategy.ask":"اسألني",
    "settings.maxWorkers":"عدد عمال المزامنة",
    "settings.versionDays":"الاحتفاظ بالإصدارات (يوم)",
    "settings.trashDays":"الاحتفاظ بسلة المحذوفات (يوم)",
    "settings.receiveFolder":"مجلد الاستقبال",
    "settings.groupKey":"مفتاح المجموعة",
    "settings.groupKeyHint":"يجب أن يكون 24 حرفاً على الأقل. شاركه فقط مع الأجهزة الموثوقة.",
    "settings.toggles":"خيارات المزامنة",
    "settings.encryption":"تشفير النقل P2P",
    "settings.compression":"ضغط الإطارات",
    "settings.watchSubs":"مراقبة المجلدات الفرعية",
    "settings.detectMoves":"اكتشاف نقل الملفات",
    "settings.blockExec":"حجب الملفات التنفيذية",
    "settings.allowReg":"السماح بالتسجيل الذاتي",
    "settings.saved":"تم حفظ الإعدادات",
    "settings.restartRequired":"أعد تشغيل الخادم لتطبيق تغيير المنفذ",
    "settings.unavailable":"الإعدادات غير متاحة",
    "login.title":"Superior Sync",
    "login.subtitle":"سجّل الدخول للمتابعة",
    "login.username":"اسم المستخدم",
    "login.password":"كلمة المرور",
    "login.submit":"تسجيل الدخول",
    "login.working":"جارٍ التحقق…",
    "login.failed":"فشل تسجيل الدخول",
    "toast.saved":"تم الحفظ",
    "toast.error":"حدث خطأ",
    "toast.networkError":"تعذّر الاتصال بالخادم",
    "toast.unauthorized":"انتهت الجلسة، يرجى تسجيل الدخول",
    "tooltip.theme":"تبديل المظهر",
    "tooltip.language":"تغيير اللغة",
    "tooltip.logout":"تسجيل الخروج",
    "misc.unknown":"غير معروف",
    "misc.folder":"مجلد",
    "misc.file":"ملف",
    "misc.free":"متاح",
  },
  en: {
    "app.tagline":"Peer-to-peer file sync",
    "nav.section.main":"Navigation",
    "nav.files":"Files",
    "nav.peers":"Peers",
    "nav.conflicts":"Conflicts",
    "nav.status":"Status",
    "nav.settings":"Settings",
    "topbar.files.title":"Files",
    "topbar.files.sub":"Browse, upload and download files",
    "topbar.peers.title":"Peers",
    "topbar.peers.sub":"Discover and manage connections",
    "topbar.conflicts.title":"Conflicts",
    "topbar.conflicts.sub":"Resolve version conflicts",
    "topbar.status.title":"Status",
    "topbar.status.sub":"Monitor the sync engine",
    "topbar.settings.title":"Settings",
    "topbar.settings.sub":"Configure sync and security",
    "common.cancel":"Cancel",
    "common.confirm":"Confirm",
    "common.close":"Close",
    "common.save":"Save",
    "common.delete":"Delete",
    "common.download":"Download",
    "common.refresh":"Refresh",
    "common.search":"Search",
    "common.loading":"Loading…",
    "common.of":"of",
    "common.actions":"Actions",
    "common.language":"Language",
    "common.theme":"Theme",
    "common.darkMode":"Dark",
    "common.lightMode":"Light",
    "common.arabic":"العربية",
    "common.english":"English",
    "files.upload":"Upload files",
    "files.searchPlaceholder":"Search in this folder…",
    "files.list":"List",
    "files.grid":"Grid",
    "files.empty":"This folder is empty",
    "files.emptyHint":"Drop files here or use the upload button to add some.",
    "files.emptySearch":"No matching files",
    "files.emptySearchHint":"Try a different search term.",
    "files.drop.title":"Drop files to upload",
    "files.drop.hint":"They will be uploaded to the current folder.",
    "files.col.name":"Name",
    "files.col.size":"Size",
    "files.col.modified":"Modified",
    "files.col.type":"Type",
    "files.confirmDelete":"Move this item to trash?",
    "files.uploading":"Uploading {name}…",
    "files.uploaded":"Uploaded {name}",
    "files.deleted":"Moved to trash",
    "files.downloaded":"Download starting…",
    "files.breadcrumbRoot":"Home",
    "peers.add":"Add peer",
    "peers.address":"Address (host:port)",
    "peers.addressPlaceholder":"192.168.1.10:8080",
    "peers.empty":"No known peers",
    "peers.emptyHint":"Add one manually or wait for automatic discovery on the LAN.",
    "peers.status.online":"Online",
    "peers.status.offline":"Offline",
    "peers.syncNow":"Sync",
    "peers.remove":"Remove",
    "peers.confirmRemove":"Remove this peer from the list?",
    "peers.added":"Peer added",
    "peers.removed":"Peer removed",
    "peers.syncTriggered":"Sync requested",
    "peers.lastSeen":"Last seen",
    "peers.never":"—",
    "peers.invalidAddress":"Use the format host:port",
    "conflicts.empty":"No conflicts",
    "conflicts.emptyHint":"All your copies are perfectly in sync. Nice!",
    "conflicts.detectedAt":"Detected",
    "conflicts.accept":"Accept",
    "conflicts.swap":"Swap",
    "conflicts.resolved":"Conflict resolved",
    "status.start":"Start",
    "status.stop":"Stop",
    "status.syncNow":"Sync now",
    "status.running":"Running",
    "status.stopped":"Stopped",
    "status.node":"Node",
    "status.files":"Indexed files",
    "status.sent":"Sent",
    "status.received":"Received",
    "status.conflicts":"Conflicts",
    "status.peersOnline":"Peers online",
    "status.errors":"Recent errors",
    "status.noErrors":"No recent errors",
    "status.lastSync":"Last sync",
    "status.never":"Never",
    "status.engineOn":"Engine started",
    "status.engineOff":"Engine stopped",
    "status.syncTriggered":"Sync cycle scheduled",
    "settings.nodeName":"Node name",
    "settings.syncInterval":"Sync interval (seconds)",
    "settings.conflictStrategy":"Conflict resolution strategy",
    "settings.strategy.newer":"Newer wins",
    "settings.strategy.older":"Older wins",
    "settings.strategy.larger":"Larger wins",
    "settings.strategy.source":"Source wins",
    "settings.strategy.target":"Target wins",
    "settings.strategy.ask":"Ask me",
    "settings.maxWorkers":"Sync workers",
    "settings.versionDays":"Version retention (days)",
    "settings.trashDays":"Trash retention (days)",
    "settings.receiveFolder":"Receive folder",
    "settings.groupKey":"Group key",
    "settings.groupKeyHint":"At least 24 characters. Share only with trusted devices.",
    "settings.toggles":"Sync options",
    "settings.encryption":"P2P transport encryption",
    "settings.compression":"Frame compression",
    "settings.watchSubs":"Watch subdirectories",
    "settings.detectMoves":"Detect file moves",
    "settings.blockExec":"Block executable files",
    "settings.allowReg":"Allow self-registration",
    "settings.saved":"Settings saved",
    "settings.restartRequired":"Restart the server to apply the new port",
    "settings.unavailable":"Settings unavailable",
    "login.title":"Superior Sync",
    "login.subtitle":"Sign in to continue",
    "login.username":"Username",
    "login.password":"Password",
    "login.submit":"Sign in",
    "login.working":"Signing in…",
    "login.failed":"Sign in failed",
    "toast.saved":"Saved",
    "toast.error":"Something went wrong",
    "toast.networkError":"Cannot reach the server",
    "toast.unauthorized":"Session expired, please sign in",
    "tooltip.theme":"Toggle theme",
    "tooltip.language":"Switch language",
    "tooltip.logout":"Sign out",
    "misc.unknown":"Unknown",
    "misc.folder":"Folder",
    "misc.file":"File",
    "misc.free":"Free",
  }
};

/* ============================================================
   ICONS
   ============================================================ */
const ICONS = {
  "home":"M3 9.5L12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-7h-6v7H4a1 1 0 0 1-1-1z",
  "folder":"M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z",
  "file":"M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6",
  "image":"M3 3h18v18H3z M8.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z M21 15l-5-5L5 21",
  "video":"M23 7l-7 5 7 5V7z M14 5H3a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2z",
  "audio":"M9 18V5l12-2v13 M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M18 19a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  "archive":"M21 8v13H3V8 M1 3h22v5H1z M10 12h4",
  "code":"M16 18l6-6-6-6 M8 6l-6 6 6 6",
  "pdf":"M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M9 13h6 M9 17h6",
  "sheet":"M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 13h8 M8 17h8 M12 13v8",
  "doc":"M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M9 13h6 M9 17h6 M9 9h2",
  "download":"M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4 M7 10l5 5 5-5 M12 15V3",
  "upload":"M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4 M17 8l-5-5-5 5 M12 3v12",
  "trash":"M3 6h18 M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6 M10 11v6 M14 11v6 M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2",
  "search":"M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z M21 21l-4.35-4.35",
  "grid":"M3 3h7v7H3z M14 3h7v7h-7z M14 14h7v7h-7z M3 14h7v7H3z",
  "list":"M8 6h13 M8 12h13 M8 18h13 M3 6h.01 M3 12h.01 M3 18h.01",
  "refresh":"M23 4v6h-6 M1 20v-6h6 M3.51 9a9 9 0 0 1 14.85-3.36L23 10 M1 14l4.64 4.36A9 9 0 0 0 20.49 15",
  "chevron-right":"M9 6l6 6-6 6",
  "chevron-down":"M6 9l6 6 6-6",
  "users":"M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M23 21v-2a4 4 0 0 0-3-3.87 M16 3.13a4 4 0 0 1 0 7.75",
  "wifi":"M5 12.55a11 11 0 0 1 14.08 0 M1.42 9a16 16 0 0 1 21.16 0 M8.53 16.11a6 6 0 0 1 6.95 0 M12 20h.01",
  "wifi-off":"M1 1l22 22 M16.72 11.06A10.94 10.94 0 0 1 19 12.55 M5 12.55a10.94 10.94 0 0 1 5.17-2.39 M10.71 5.05A16 16 0 0 1 22.58 9 M1.42 9a15.91 15.91 0 0 1 4.7-2.88 M8.53 16.11a6 6 0 0 1 6.95 0 M12 20h.01",
  "plus":"M12 5v14 M5 12h14",
  "x":"M18 6L6 18 M6 6l12 12",
  "sync":"M21.5 2v6h-6 M2.5 22v-6h6 M2 11.5a10 10 0 0 1 18.8-4.3 M22 12.5a10 10 0 0 1-18.8 4.2",
  "alert-triangle":"M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z M12 9v4 M12 17h.01",
  "alert-circle":"M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z M12 8v4 M12 16h.01",
  "check":"M20 6L9 17l-5-5",
  "check-circle":"M22 11.08V12a10 10 0 1 1-5.93-9.14 M22 4L12 14.01l-3-3",
  "swap":"M17 1l4 4-4 4 M3 11V9a4 4 0 0 1 4-4h14 M7 23l-4-4 4-4 M21 13v2a4 4 0 0 1-4 4H3",
  "activity":"M22 12h-4l-3 9L9 3l-3 9H2",
  "cpu":"M4 4h16v16H4z M9 9h6v6H9z M9 1v3 M15 1v3 M9 20v3 M15 20v3 M20 9h3 M20 14h3 M1 9h3 M1 14h3",
  "hard-drive":"M22 12H2 M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z M6 16h.01 M10 16h.01",
  "zap":"M13 2L3 14h9l-1 8 10-12h-9l1-8z",
  "settings":"M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z",
  "log-out":"M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4 M16 17l5-5-5-5 M21 12H9",
  "menu":"M3 12h18 M3 6h18 M3 18h18",
  "globe":"M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z M2 12h20 M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z",
  "sun":"M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z M12 1v2 M12 21v2 M4.22 4.22l1.42 1.42 M18.36 18.36l1.42 1.42 M1 12h2 M21 12h2 M4.22 19.78l1.42-1.42 M18.36 5.64l1.42-1.42",
  "moon":"M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z",
  "info":"M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z M12 16v-4 M12 8h.01",
  "server":"M4 4h16v6H4z M4 14h16v6H4z M7 7h.01 M7 17h.01",
  "shield":"M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  "eye":"M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  "eye-off":"M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24 M1 1l22 22",
  "more":"M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z M19 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z M5 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  "git-branch":"M6 3v12 M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M18 9a9 9 0 0 1-9 9",
  "inbox":"M22 12h-6l-2 3h-4l-2-3H2 M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z",
};

/* ============================================================
   HELPERS
   ============================================================ */
const SVG_NS = "http://www.w3.org/2000/svg";
const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

function el(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "on") {
        for (const [ev, fn] of Object.entries(v)) node.addEventListener(ev, fn);
      } else if (k === "style" && typeof v === "object") {
        Object.assign(node.style, v);
      } else if (k === "dataset" && typeof v === "object") {
        Object.assign(node.dataset, v);
      } else if (v === true) node.setAttribute(k, "");
      else node.setAttribute(k, v);
    }
  }
  append(node, kids);
  return node;
}

function append(parent, kids) {
  for (const kid of kids) {
    if (kid == null || kid === false || kid === "") continue;
    if (Array.isArray(kid)) append(parent, kid);
    else if (kid.nodeType) parent.append(kid);
    else parent.append(document.createTextNode(String(kid)));
  }
}

function icon(name, size) {
  const s = document.createElementNS(SVG_NS, "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("width", size || 18);
  s.setAttribute("height", size || 18);
  s.setAttribute("fill", "none");
  s.setAttribute("stroke", "currentColor");
  s.setAttribute("stroke-width", "1.8");
  s.setAttribute("stroke-linecap", "round");
  s.setAttribute("stroke-linejoin", "round");
  s.setAttribute("class", "icon");
  s.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(SVG_NS, "path");
  p.setAttribute("d", ICONS[name] || ICONS.file);
  s.append(p);
  return s;
}

function svgPath(name, size) {
  const s = document.createElementNS(SVG_NS, "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("width", size || 18);
  s.setAttribute("height", size || 18);
  s.setAttribute("fill", "none");
  s.setAttribute("stroke", "currentColor");
  s.setAttribute("stroke-width", "1.8");
  s.setAttribute("stroke-linecap", "round");
  s.setAttribute("stroke-linejoin", "round");
  s.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(SVG_NS, "path");
  p.setAttribute("d", ICONS[name] || ICONS.file);
  s.append(p);
  return s;
}

function t(key, vars) {
  const table = I18N[state.lang] || I18N.en;
  let text = table[key];
  if (text == null) text = I18N.en[key];
  if (text == null) return key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      text = text.split("{" + k + "}").join(String(v));
    }
  }
  return text;
}

const fmt = {
  size(n) {
    n = Number(n) || 0;
    if (n < 1024) return n + " B";
    const units = ["KB", "MB", "GB", "TB", "PB"];
    let i = -1;
    do { n /= 1024; i++; } while (n >= 1024 && i < units.length - 1);
    return (n >= 100 ? n.toFixed(0) : n.toFixed(1)) + " " + units[i];
  },
  time(ts) {
    if (!ts) return "—";
    const d = new Date(Number(ts) * 1000);
    const now = Date.now();
    const diff = (now - d.getTime()) / 1000;
    if (diff < 60) return state.lang === "ar" ? "الآن" : "just now";
    if (diff < 3600) {
      const m = Math.floor(diff / 60);
      return state.lang === "ar" ? `قبل ${m} د` : `${m}m ago`;
    }
    if (diff < 86400) {
      const h = Math.floor(diff / 3600);
      return state.lang === "ar" ? `قبل ${h} س` : `${h}h ago`;
    }
    return d.toLocaleDateString(state.lang === "ar" ? "ar" : "en", {
      year: "numeric", month: "short", day: "numeric"
    });
  },
  date(ts) {
    if (!ts) return "—";
    return new Date(Number(ts) * 1000).toLocaleString(
      state.lang === "ar" ? "ar" : "en",
      { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }
};

function extOf(name) {
  const m = String(name || "").toLowerCase().match(/\.([a-z0-9]+)$/);
  return m ? m[1] : "";
}

const FILE_KINDS = {
  image: ["jpg","jpeg","png","gif","webp","svg","bmp","ico","tif","tiff","avif"],
  video: ["mp4","webm","mkv","mov","avi","flv","wmv","m4v"],
  audio: ["mp3","wav","ogg","flac","m4a","aac","opus","wma"],
  archive: ["zip","tar","gz","tgz","bz2","7z","rar","xz","zst"],
  pdf: ["pdf"],
  doc: ["doc","docx","txt","md","rtf","odt","pages"],
  sheet: ["xls","xlsx","csv","ods","numbers"],
  code: ["py","js","ts","jsx","tsx","html","htm","css","scss","json","xml","yml","yaml","sh","bash","go","rs","java","c","cpp","h","hpp","rb","php","swift","kt","sql"],
};

function fileIcon(name) {
  const ext = extOf(name);
  if (!ext) return "file";
  for (const [kind, exts] of Object.entries(FILE_KINDS)) {
    if (exts.includes(ext)) return kind;
  }
  return "file";
}

/* ============================================================
   STATE
   ============================================================ */
const state = {
  lang: localStorage.getItem("ss.lang") || "ar",
  theme: localStorage.getItem("ss.theme") || "dark",
  view: (location.hash.replace(/^#\/?/, "") || "files"),
  share: "received",
  folder: "",
  search: "",
  layout: localStorage.getItem("ss.layout") || "list",
  user: null,
  shares: [],
  files: [],
  peers: [],
  conflicts: [],
  status: null,
  config: null,
  busy: false,
  error: null,
};

/* ============================================================
   API
   ============================================================ */
async function api(method, path, body, opts) {
  opts = opts || {};
  const init = {
    method,
    credentials: "same-origin",
    headers: {
      "Accept-Language": state.lang,
      "X-Requested-With": "SuperiorSync",
    },
  };
  if (typeof LOCAL_TOKEN === "string" && LOCAL_TOKEN) {
    init.headers["X-SS-Local-Token"] = LOCAL_TOKEN;
  }
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const sep = path.includes("?") ? "&" : "?";
  const url = path + sep + "lang=" + encodeURIComponent(state.lang);
  let res;
  try {
    res = await fetch(url, init);
  } catch (e) {
    throw new Error(t("toast.networkError"));
  }
  if (res.status === 401 && !opts.allowUnauth) {
    state.user = null;
    render();
    throw new Error("unauthorized");
  }
  if (opts.raw) return res;
  if (opts.blob) return res.blob();
  let data = null;
  const text = await res.text();
  if (text) { try { data = JSON.parse(text); } catch { data = null; } }
  if (!res.ok) {
    let msg = (data && (data.error || data.detail)) || ("HTTP " + res.status);
    if (typeof msg !== "string") msg = JSON.stringify(msg);
    throw new Error(msg);
  }
  return data;
}

function uploadFile(share, folder, file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const fd = new FormData();
    fd.append("file", file, file.name);
    const url = "/api/files/upload?share=" + encodeURIComponent(share)
              + "&folder=" + encodeURIComponent(folder)
              + "&lang=" + encodeURIComponent(state.lang);
    xhr.open("POST", url);
    xhr.setRequestHeader("X-Requested-With", "SuperiorSync");
    xhr.setRequestHeader("Accept-Language", state.lang);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)); } catch { resolve({}); }
      } else {
        let msg = "HTTP " + xhr.status;
        try {
          const d = JSON.parse(xhr.responseText);
          msg = d.error || d.detail || msg;
        } catch {}
        reject(new Error(typeof msg === "string" ? msg : JSON.stringify(msg)));
      }
    };
    xhr.onerror = () => reject(new Error(t("toast.networkError")));
    xhr.send(fd);
  });
}

/* ============================================================
   TOASTS
   ============================================================ */
function toast(message, kind) {
  kind = kind || "info";
  const stack = $("#toasts");
  if (!stack) return;
  const iconName = kind === "success" ? "check-circle"
                : kind === "error" ? "alert-circle"
                : kind === "warning" ? "alert-triangle" : "info";
  const node = el("div", { class: "toast " + kind, role: "status" },
    el("span", { class: "toast-icon" }, svgPath(iconName, 18)),
    el("div", { class: "toast-body" },
      el("p", null, message)),
    el("button", { class: "close", type: "button", "aria-label": t("common.close"),
      on: { click: () => dismiss() } }, svgPath("x", 14))
  );
  stack.append(node);
  const timer = setTimeout(dismiss, 4200);
  function dismiss() {
    clearTimeout(timer);
    node.classList.add("out");
    setTimeout(() => node.remove(), 180);
  }
}

/* ============================================================
   MODAL
   ============================================================ */
function openModal(opts) {
  const root = $("#modalRoot");
  const buttons = (opts.buttons || []).map(b =>
    el("button", {
      class: "btn " + (b.variant || ""),
      type: "button",
      on: { click: () => { if (b.onClick) b.onClick(); if (b.close !== false) closeModal(); } }
    }, b.label)
  );
  const modal = el("div", { class: "modal", role: "dialog", "aria-modal": "true",
    on: { click: e => e.stopPropagation() } },
    el("div", { class: "modal-head" },
      el("h3", null, opts.title || ""),
      opts.subtitle ? el("p", null, opts.subtitle) : null
    ),
    opts.body ? el("div", { class: "modal-body" }, opts.body) : null,
    el("div", { class: "modal-foot" }, buttons)
  );
  root.replaceChildren(modal);
  root.hidden = false;
  root.setAttribute("aria-hidden", "false");
  root.onclick = closeModal;
  const focusable = modal.querySelector("button, input, select, textarea, [tabindex]");
  if (focusable) focusable.focus();
  document.addEventListener("keydown", onKey);
  function onKey(e) { if (e.key === "Escape") closeModal(); }
  function closeModal() {
    root.hidden = true;
    root.setAttribute("aria-hidden", "true");
    root.replaceChildren();
    root.onclick = null;
    document.removeEventListener("keydown", onKey);
  }
  return { close: closeModal };
}

function confirmDialog(title, message, onConfirm) {
  const m = openModal({
    title,
    subtitle: message,
    buttons: [
      { label: t("common.cancel"), variant: "subtle" },
      { label: t("common.confirm"), variant: "primary", onClick: onConfirm },
    ]
  });
  return m;
}

/* ============================================================
   VIEWS
   ============================================================ */
const NAV_ITEMS = [
  { id: "files",     label: "nav.files",     icon: "folder" },
  { id: "peers",     label: "nav.peers",     icon: "users" },
  { id: "conflicts", label: "nav.conflicts", icon: "alert-triangle" },
  { id: "status",    label: "nav.status",    icon: "activity" },
  { id: "settings",  label: "nav.settings",  icon: "settings" },
];

function renderSidebar() {
  const nav = $("#nav");
  if (!nav) return;
  nav.replaceChildren();

  const section = el("div", { class: "nav-section" }, t("nav.section.main"));
  nav.append(section);

  for (const item of NAV_ITEMS) {
    if (!state.user) break;
    const badgeCount = item.id === "conflicts" && state.conflicts.length
      ? state.conflicts.length : null;
    const btn = el("button", {
      class: "nav-item" + (state.view === item.id ? " active" : ""),
      type: "button",
      on: { click: () => navigate(item.id) }
    },
      icon(item.icon, 18),
      el("span", null, t(item.label)),
      badgeCount ? el("span", { class: "nav-badge" }, String(badgeCount)) : null
    );
    nav.append(btn);
  }

  // Footer user chip
  const chip = $("#userChip");
  if (!chip) return;
  chip.replaceChildren();
  if (state.user) {
    const initials = (state.user.username || "?").slice(0, 2).toUpperCase();
    chip.append(
      el("div", { class: "avatar" }, initials),
      el("div", { class: "user-info" },
        el("strong", null, state.user.username || ""),
        el("span", null, state.user.role || "")
      ),
      el("button", { class: "logout-btn", type: "button",
        title: t("tooltip.logout"), "aria-label": t("tooltip.logout"),
        on: { click: logout } }, svgPath("log-out", 16))
    );
  }

  // Localized small labels
  const tagline = $("#brandTagline");
  if (tagline) tagline.textContent = t("app.tagline");

  const themeLabel = $("#themeLabel");
  const langLabel = $("#langLabel");
  const themeIcon = $("#themeIcon");
  const langIcon = $("#langIcon");
  if (themeIcon) themeIcon.replaceChildren(svgPath(state.theme === "dark" ? "moon" : "sun", 14));
  if (langIcon) langIcon.replaceChildren(svgPath("globe", 14));
  if (themeLabel) themeLabel.textContent = state.theme === "dark" ? t("common.darkMode") : t("common.lightMode");
  if (langLabel) langLabel.textContent = state.lang === "ar" ? t("common.english") : t("common.arabic");

  const themeBtn = $("#themeBtn");
  const langBtn = $("#langBtn");
  if (themeBtn) themeBtn.title = t("tooltip.theme");
  if (langBtn) langBtn.title = t("tooltip.language");
}

function renderTopbar(actions) {
  const title = $("#topbarTitle");
  const actions_ = $("#topbarActions");
  if (title) {
    title.replaceChildren();
    if (state.user) {
      title.append(
        el("h1", null, t("topbar." + state.view + ".title")),
        el("p", null, t("topbar." + state.view + ".sub"))
      );
    }
  }
  if (actions_) {
    actions_.replaceChildren();
    if (actions) append(actions_, [actions]);
  }
}

async function viewFiles(actionsHost) {
  const root = el("div", null);
  if (!state.shares.length) {
    try {
      state.shares = await api("GET", "/api/files/shares");
      if (!state.shares.length) state.shares = [{ id: "received", path: "" }];
      if (!state.shares.find(s => s.id === state.share)) {
        state.share = state.shares[0].id;
      }
    } catch (e) {
      if (e.message === "unauthorized") return root;
      root.append(emptyState("alert-circle", e.message));
      return root;
    }
  }

  const searchInput = el("input", {
    class: "input search-input",
    type: "search",
    placeholder: t("files.searchPlaceholder"),
    value: state.search,
    "aria-label": t("common.search"),
    on: {
      input: (e) => { state.search = e.target.value; filterFiles(); },
      keydown: (e) => { if (e.key === "Escape") { e.target.value = ""; state.search = ""; filterFiles(); } }
    }
  });

  const layoutToggle = el("div", { class: "segmented", role: "group" },
    el("button", {
      type: "button", class: state.layout === "list" ? "active" : "",
      "aria-pressed": state.layout === "list" ? "true" : "false",
      on: { click: () => setLayout("list") }
    }, svgPath("list", 14), el("span", null, t("files.list"))),
    el("button", {
      type: "button", class: state.layout === "grid" ? "active" : "",
      "aria-pressed": state.layout === "grid" ? "true" : "false",
      on: { click: () => setLayout("grid") }
    }, svgPath("grid", 14), el("span", null, t("files.grid")))
  );

  const fileInput = el("input", {
    type: "file", multiple: true, style: { display: "none" },
    on: {
      change: async (e) => {
        const files = Array.from(e.target.files || []);
        e.target.value = "";
        if (files.length) await uploadFiles(files);
      }
    }
  });

  const shareSelect = el("select", {
    class: "select", "aria-label": t("files.col.name"),
    on: { change: (e) => { state.share = e.target.value; state.folder = ""; state.search = ""; render(); } }
  }, state.shares.map(s => el("option", {
    value: s.id, selected: s.id === state.share ? true : null
  }, s.id)));

  const crumbs = buildBreadcrumbs();

  const toolbar = el("div", { class: "toolbar" },
    el("div", { class: "input-group", style: { flex: "1", maxWidth: "280px" } },
      svgPath("search", 16).cloneNode ? Object.assign(svgPath("search", 16), { class: "input-icon" }) : null,
      searchInput
    ),
    el("div", { class: "grow" }),
    shareSelect,
    layoutToggle,
    el("button", {
      class: "btn subtle", type: "button",
      on: { click: () => refreshFiles() }
    }, svgPath("refresh", 16), el("span", null, t("common.refresh"))),
    el("button", {
      class: "btn primary", type: "button",
      on: { click: () => fileInput.click() }
    }, svgPath("upload", 16), el("span", null, t("files.upload"))),
    fileInput
  );

  const body = el("div", { id: "filesBody" });

  // Build content
  await loadFilesContent(body);

  root.append(
    el("div", { style: { marginBottom: "16px", display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" } },
      el("div", { class: "crumbs", "aria-label": "Breadcrumb" }, crumbs)
    ),
    toolbar,
    body
  );

  // Attach drag-and-drop for the whole view
  root.addEventListener("dragover", (e) => { e.preventDefault(); showDropOverlay(true); });
  root.addEventListener("dragleave", (e) => {
    if (!root.contains(e.relatedTarget)) showDropOverlay(false);
  });
  root.addEventListener("drop", async (e) => {
    e.preventDefault();
    showDropOverlay(false);
    const files = Array.from(e.dataTransfer.files || []);
    if (files.length) await uploadFiles(files);
  });

  return root;
}

function buildBreadcrumbs() {
  const parts = [];
  parts.push(el("button", {
    type: "button", class: !state.folder ? "current" : "",
    on: { click: () => { if (state.folder) { state.folder = ""; state.search = ""; render(); } } }
  }, svgPath("home", 14), " " + state.share));
  if (state.folder) {
    const segs = state.folder.split("/").filter(Boolean);
    let acc = "";
    segs.forEach((seg, i) => {
      acc = acc ? acc + "/" + seg : seg;
      const target = acc;
      parts.push(el("span", { class: "sep" }, svgPath("chevron-right", 12)));
      parts.push(el("button", {
        type: "button", class: i === segs.length - 1 ? "current" : "",
        on: { click: () => { if (i !== segs.length - 1) { state.folder = target; state.search = ""; render(); } } }
      }, seg));
    });
  }
  return parts;
}

async function loadFilesContent(host) {
  host.replaceChildren(renderSkeleton(6));
  try {
    const data = await api("GET",
      "/api/files?share=" + encodeURIComponent(state.share)
      + "&folder=" + encodeURIComponent(state.folder));
    state.files = (data && data.files) || [];
  } catch (e) {
    host.replaceChildren(emptyState("alert-circle", e.message));
    return;
  }
  renderFilesBody(host);
}

function renderFilesBody(host) {
  const filtered = state.search
    ? state.files.filter(f => f.name.toLowerCase().includes(state.search.toLowerCase()))
    : state.files;

  if (!state.files.length) {
    host.replaceChildren(emptyState("folder", t("files.empty"), t("files.emptyHint")));
    return;
  }
  if (!filtered.length) {
    host.replaceChildren(emptyState("search", t("files.emptySearch"), t("files.emptySearchHint")));
    return;
  }

  if (state.layout === "grid") {
    host.replaceChildren(el("div", { class: "file-grid" },
      filtered.map(f => fileTile(f))));
  } else {
    host.replaceChildren(el("div", { class: "card" },
      el("div", { class: "table-wrap" }, el("table", null,
        el("thead", null, el("tr", null,
          el("th", null, t("files.col.name")),
          el("th", { style: { width: "110px" } }, t("files.col.size")),
          el("th", { style: { width: "160px" } }, t("files.col.modified")),
          el("th", { style: { width: "120px", textAlign: "end" } }, t("common.actions"))
        )),
        el("tbody", null, filtered.map(f => fileRow(f)))
      ))
    ));
  }
}

function filterFiles() {
  const host = $("#filesBody");
  if (host) renderFilesBody(host);
}

function fileRow(f) {
  const isFolder = f.type === "folder";
  return el("tr", null,
    el("td", null,
      el("div", { class: "file-name" + (isFolder ? " folder" : ""),
        on: isFolder ? { click: () => { state.folder = f.path; state.search = ""; render(); } } : null },
        svgPath(isFolder ? "folder" : fileIcon(f.name), 18),
        el("span", { class: "name truncate" }, f.name)
      )
    ),
    el("td", { class: "mono" }, isFolder ? "—" : fmt.size(f.size)),
    el("td", { class: "muted" }, fmt.time(f.modified)),
    el("td", null, el("div", { class: "cell-actions" },
      isFolder ? null : el("button", {
        class: "btn sm subtle", type: "button",
        title: t("common.download"),
        on: { click: () => downloadFile(f) }
      }, svgPath("download", 14)),
      el("button", {
        class: "btn sm danger", type: "button",
        title: t("common.delete"),
        on: { click: () => deleteFile(f) }
      }, svgPath("trash", 14))
    ))
  );
}

function fileTile(f) {
  const isFolder = f.type === "folder";
  return el("div", {
    class: "file-tile",
    on: { click: () => { if (isFolder) { state.folder = f.path; state.search = ""; render(); } } }
  },
    el("div", { class: "tile-actions" },
      isFolder ? null : el("button", {
        class: "icon-btn", type: "button", title: t("common.download"),
        on: { click: (e) => { e.stopPropagation(); downloadFile(f); } }
      }, svgPath("download", 14)),
      el("button", {
        class: "icon-btn", type: "button", title: t("common.delete"),
        on: { click: (e) => { e.stopPropagation(); deleteFile(f); } }
      }, svgPath("trash", 14))
    ),
    el("div", { class: "tile-icon" + (isFolder ? " folder" : "") },
      svgPath(isFolder ? "folder" : fileIcon(f.name), 22)),
    el("div", { class: "tile-meta" },
      el("span", { class: "name" }, f.name),
      el("span", { class: "sub" }, isFolder ? t("misc.folder") : fmt.size(f.size) + " · " + fmt.time(f.modified))
    )
  );
}

async function downloadFile(f) {
  try {
    const res = await api("GET",
      "/api/files/download?share=" + encodeURIComponent(state.share)
      + "&path=" + encodeURIComponent(f.path), undefined, { raw: true });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = el("a", { href: url, download: f.name, style: { display: "none" } });
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
    toast(t("files.downloaded", { name: f.name }), "success");
  } catch (e) {
    if (e.message !== "unauthorized") toast(e.message, "error");
  }
}

function deleteFile(f) {
  confirmDialog(t("common.delete"), t("files.confirmDelete"), async () => {
    try {
      await api("DELETE",
        "/api/files?share=" + encodeURIComponent(state.share)
        + "&path=" + encodeURIComponent(f.path));
      toast(t("files.deleted"), "success");
      refreshFiles();
    } catch (e) {
      if (e.message !== "unauthorized") toast(e.message, "error");
    }
  });
}

async function uploadFiles(files) {
  for (const f of files) {
    const tid = toast(t("files.uploading", { name: f.name }), "info");
    try {
      await uploadFile(state.share, state.folder, f);
      toast(t("files.uploaded", { name: f.name }), "success");
    } catch (e) {
      if (e.message !== "unauthorized") toast(e.message, "error");
    }
  }
  refreshFiles();
}

function setLayout(layout) {
  state.layout = layout;
  localStorage.setItem("ss.layout", layout);
  render();
}

async function refreshFiles() {
  const host = $("#filesBody");
  if (host) await loadFilesContent(host);
}

function showDropOverlay(show) {
  const o = $("#dropOverlay");
  if (!o) return;
  o.classList.toggle("active", !!show);
}

/* ---------------------------------------------------------- PEERS */
async function viewPeers() {
  const root = el("div", null);

  try {
    const data = await api("GET", "/api/peers");
    state.peers = (data && data.peers) || [];
  } catch (e) {
    if (e.message === "unauthorized") return root;
    root.append(emptyState("alert-circle", e.message));
    return root;
  }

  const addr = el("input", {
    class: "input",
    placeholder: t("peers.addressPlaceholder"),
    "aria-label": t("peers.address"),
    on: { keydown: (e) => { if (e.key === "Enter") addPeer(addr.value); } }
  });

  root.append(
    el("div", { class: "card", style: { marginBottom: "16px" } },
      el("div", { class: "card-body" },
        el("div", { class: "row wrap" },
          el("div", { class: "grow", style: { minWidth: "220px" } }, addr),
          el("button", {
            class: "btn primary", type: "button",
            on: { click: () => addPeer(addr.value) }
          }, svgPath("plus", 16), el("span", null, t("peers.add")))
        )
      )
    )
  );

  if (!state.peers.length) {
    root.append(emptyState("users", t("peers.empty"), t("peers.emptyHint")));
    return root;
  }

  const grid = el("div", { class: "peer-grid" }, state.peers.map(p => peerCard(p)));
  root.append(grid);
  return root;
}

function peerCard(p) {
  const online = p.status === "online";
  const initials = (p.name || p.id || "?").slice(0, 2).toUpperCase();
  return el("div", { class: "peer-card" },
    el("div", { class: "peer-head" },
      el("div", { class: "peer-avatar" + (online ? " online" : "") },
        el("span", null, initials),
        el("span", { class: "status-dot" })
      ),
      el("div", { class: "peer-head-info" },
        el("strong", null, p.name || p.id),
        el("span", null, p.ip + ":" + p.port)
      ),
      el("span", { class: "badge " + (online ? "success" : "") },
        el("span", { class: "dot" }),
        online ? t("peers.status.online") : t("peers.status.offline"))
    ),
    el("div", { class: "peer-meta" },
      el("div", { class: "row" },
        el("span", null, t("peers.lastSeen")),
        el("span", null, p.last_seen ? fmt.time(p.last_seen) : t("peers.never"))
      ),
      p.shares && p.shares.length ? el("div", { class: "row" },
        el("span", null, "Shares"),
        el("span", null, p.shares.slice(0, 3).join(", ") + (p.shares.length > 3 ? "…" : ""))
      ) : null
    ),
    el("div", { class: "peer-actions" },
      el("button", {
        class: "btn sm", type: "button",
        on: { click: () => syncPeer(p) }
      }, svgPath("sync", 14), el("span", null, t("peers.syncNow"))),
      el("button", {
        class: "btn sm danger", type: "button",
        on: { click: () => removePeer(p) }
      }, svgPath("trash", 14), el("span", null, t("peers.remove")))
    )
  );
}

async function addPeer(address) {
  address = (address || "").trim();
  if (!/^[^\s:]+:\d{1,5}$/.test(address)) {
    toast(t("peers.invalidAddress"), "error");
    return;
  }
  try {
    await api("POST", "/api/peers", { address });
    toast(t("peers.added"), "success");
    render();
  } catch (e) {
    if (e.message !== "unauthorized") toast(e.message, "error");
  }
}

function removePeer(p) {
  confirmDialog(t("peers.remove"), t("peers.confirmRemove"), async () => {
    try {
      await api("DELETE", "/api/peers/" + encodeURIComponent(p.id));
      toast(t("peers.removed"), "success");
      render();
    } catch (e) {
      if (e.message !== "unauthorized") toast(e.message, "error");
    }
  });
}

async function syncPeer(p) {
  try {
    await api("POST", "/api/peers/" + encodeURIComponent(p.id) + "/sync");
    toast(t("peers.syncTriggered"), "success");
  } catch (e) {
    if (e.message !== "unauthorized") toast(e.message, "error");
  }
}

/* ---------------------------------------------------------- CONFLICTS */
async function viewConflicts() {
  const root = el("div", null);
  try {
    const data = await api("GET", "/api/conflicts?open=true");
    state.conflicts = (data && data.conflicts) || [];
  } catch (e) {
    if (e.message === "unauthorized") return root;
    root.append(emptyState("alert-circle", e.message));
    return root;
  }

  if (!state.conflicts.length) {
    root.append(emptyState("check-circle", t("conflicts.empty"), t("conflicts.emptyHint")));
    return root;
  }

  root.append(el("div", { class: "card" },
    el("div", { class: "conflict-list", style: { padding: "12px" } },
      state.conflicts.map(c => conflictRow(c)))
  ));
  return root;
}

function conflictRow(c) {
  return el("div", { class: "conflict-row" },
    el("div", { class: "conflict-icon" }, svgPath("alert-triangle", 18)),
    el("div", { class: "conflict-body" },
      el("div", { class: "path" }, c.path),
      el("div", { class: "sub" }, c.share + " · " + fmt.date(c.detected_at))
    ),
    el("div", { class: "conflict-actions" },
      el("button", {
        class: "btn sm", type: "button",
        on: { click: () => resolveConflict(c, "accept") }
      }, svgPath("check", 14), el("span", null, t("conflicts.accept"))),
      c.copy_path ? el("button", {
        class: "btn sm", type: "button",
        on: { click: () => resolveConflict(c, "swap") }
      }, svgPath("swap", 14), el("span", null, t("conflicts.swap"))) : null
    )
  );
}

async function resolveConflict(c, action) {
  try {
    await api("POST", "/api/conflicts/" + encodeURIComponent(c.id) + "/resolve", { action });
    toast(t("conflicts.resolved"), "success");
    render();
  } catch (e) {
    if (e.message !== "unauthorized") toast(e.message, "error");
  }
}

/* ---------------------------------------------------------- STATUS */
async function viewStatus(actionsHost) {
  const root = el("div", null);
  try {
    const data = await api("GET", "/api/sync/status");
    state.status = data || null;
  } catch (e) {
    if (e.message === "unauthorized") return root;
    root.append(emptyState("alert-circle", e.message));
    return root;
  }

  const d = state.status || {};
  const stats = d.stats || {};
  const tr = stats.transfer || {};
  const st = stats.sync_state || {};

  // Toolbar actions
  if (actionsHost) {
    actionsHost.append(
      el("button", {
        class: "btn", type: "button",
        on: { click: () => syncNow() }
      }, svgPath("sync", 16), el("span", null, t("status.syncNow"))),
      el("button", {
        class: "btn " + (d.status === "running" ? "danger" : "primary"),
        type: "button",
        on: { click: () => toggleEngine(d.status !== "running") }
      }, svgPath(d.status === "running" ? "x" : "zap", 16),
         el("span", null, d.status === "running" ? t("status.stop") : t("status.start")))
    );
  }

  // Stat cards
  const statusKind = d.status === "running" ? "green" : "red";
  const statusLabel = d.status === "running" ? t("status.running") : t("status.stopped");

  const statGrid = el("div", { class: "stat-grid" },
    statCard("activity", t("status.node"), stats.node ? stats.node.name : "—",
      stats.node ? stats.node.id : "", "blue", "sm"),
    statCard("zap", t("status.files"), String(stats.sync_records_count || 0), "", "purple"),
    statCard("users", t("status.peersOnline"),
      String((stats.p2p_protocol && stats.p2p_protocol.peers_online) || 0), "", "cyan"),
    statCard("alert-triangle", t("status.conflicts"),
      String((tr.conflicts) || 0), "", "amber"),
    statCard("download", t("status.received"), fmt.size(tr.bytes_received || 0), "", "green"),
    statCard("upload", t("status.sent"), fmt.size(tr.bytes_sent || 0), "", "blue"),
  );

  root.append(statGrid);

  // Engine status bar
  root.append(el("div", { class: "card", style: { marginBottom: "16px" } },
    el("div", { class: "card-body", style: { display: "flex", alignItems: "center", gap: "16px", flexWrap: "wrap" } },
      el("span", { class: "badge " + (d.status === "running" ? "success" : "danger") },
        el("span", { class: "dot" }), statusLabel),
      el("span", { class: "muted small" },
        t("status.lastSync") + ": " + (st.last_sync ? fmt.date(st.last_sync) : t("status.never")))
    )
  ));

  // Errors
  const errors = (st.errors || []).slice(-5).reverse();
  root.append(el("div", { class: "card" },
    el("div", { class: "card-header" },
      svgPath("alert-circle", 16),
      el("h2", null, t("status.errors"))
    ),
    errors.length
      ? el("div", { class: "table-wrap" }, el("table", null,
          el("tbody", null, errors.map(er => el("tr", null,
            el("td", { style: { width: "160px" } }, el("span", { class: "muted small" }, fmt.date(er.time))),
            el("td", null, el("span", { class: "mono" }, er.error))
          )))
        ))
      : el("div", { class: "card-body" },
          el("p", { class: "muted" }, t("status.noErrors")))
  ));

  return root;
}

function statCard(iconName, label, value, sub, accent, sizeClass) {
  return el("div", { class: "stat " + (accent || "") },
    el("div", { class: "stat-accent" }),
    el("div", { class: "stat-label" }, svgPath(iconName, 14), el("span", null, label)),
    el("div", { class: "stat-value" + (sizeClass === "sm" ? " sm" : "") }, value),
    sub ? el("div", { class: "stat-sub" }, sub) : null
  );
}

async function toggleEngine(on) {
  try {
    await api("POST", on ? "/api/sync/start" : "/api/sync/stop");
    toast(on ? t("status.engineOn") : t("status.engineOff"), "success");
    render();
  } catch (e) {
    if (e.message !== "unauthorized") toast(e.message, "error");
  }
}

async function syncNow() {
  try {
    await api("POST", "/api/sync/now");
    toast(t("status.syncTriggered"), "success");
  } catch (e) {
    if (e.message !== "unauthorized") toast(e.message, "error");
  }
}

/* ---------------------------------------------------------- SETTINGS */
async function viewSettings() {
  const root = el("div", null);
  let cfg;
  try {
    cfg = await api("GET", "/api/config");
    state.config = cfg;
  } catch (e) {
    if (e.message === "unauthorized") return root;
    root.append(emptyState("alert-circle", e.message));
    return root;
  }

  const draft = {};
  const field = (key, label, type, opts) => {
    opts = opts || {};
    const value = cfg[key];
    let input;
    if (type === "toggle") {
      const chk = el("input", { type: "checkbox", checked: !!value,
        on: { change: (e) => { draft[key] = e.target.checked; } } });
      input = el("label", { class: "switch" }, chk, el("span", { class: "switch-track" }));
    } else if (type === "select") {
      input = el("select", { class: "select", on: { change: (e) => { draft[key] = e.target.value; } } },
        opts.options.map(o => el("option", { value: o.value, selected: value === o.value ? true : null }, o.label))
      );
    } else if (type === "password") {
      const inp = el("input", { class: "input", type: "password", value: value || "",
        on: { input: (e) => { draft[key] = e.target.value; } } });
      const eye = el("button", {
        class: "icon-btn", type: "button", "aria-label": "toggle visibility",
        on: { click: () => { inp.type = inp.type === "password" ? "text" : "password"; } }
      }, svgPath("eye", 16));
      input = el("div", { class: "row" }, el("div", { class: "grow" }, inp), eye);
    } else {
      input = el("input", { class: "input", type: type || "text", value: value || "",
        placeholder: opts.placeholder || "",
        on: { input: (e) => { draft[key] = type === "number" ? Number(e.target.value) : e.target.value; } } });
    }
    return el("div", { class: "field" },
      el("label", null, label),
      input,
      opts.hint ? el("div", { class: "field-hint" }, opts.hint) : null
    );
  };

  root.append(el("div", { class: "card", style: { marginBottom: "16px" } },
    el("div", { class: "card-header" },
      svgPath("server", 16), el("h2", null, t("settings.nodeName"))),
    el("div", { class: "card-body", style: { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: "16px" } },
      field("node_name", t("settings.nodeName"), "text"),
      field("sync_interval", t("settings.syncInterval"), "number"),
      field("max_workers", t("settings.maxWorkers"), "number"),
      field("receive_folder", t("settings.receiveFolder"), "text"),
    )
  ));

  root.append(el("div", { class: "card", style: { marginBottom: "16px" } },
    el("div", { class: "card-header" },
      svgPath("git-branch", 16), el("h2", null, t("settings.conflictStrategy"))),
    el("div", { class: "card-body", style: { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: "16px" } },
      field("conflict_resolution", t("settings.conflictStrategy"), "select", {
        options: [
          { value: "newer", label: t("settings.strategy.newer") },
          { value: "older", label: t("settings.strategy.older") },
          { value: "larger", label: t("settings.strategy.larger") },
          { value: "source", label: t("settings.strategy.source") },
          { value: "target", label: t("settings.strategy.target") },
          { value: "ask", label: t("settings.strategy.ask") },
        ]
      }),
      field("version_retention_days", t("settings.versionDays"), "number"),
      field("trash_retention_days", t("settings.trashDays"), "number"),
    )
  ));

  root.append(el("div", { class: "card", style: { marginBottom: "16px" } },
    el("div", { class: "card-header" },
      svgPath("shield", 16), el("h2", null, t("settings.groupKey"))),
    el("div", { class: "card-body" },
      field("group_key", t("settings.groupKey"), "password", {
        hint: t("settings.groupKeyHint")
      })
    )
  ));

  const toggles = [
    ["enable_encryption", "settings.encryption", "shield"],
    ["enable_compression", "settings.compression", "zap"],
    ["watch_subdirectories", "settings.watchSubs", "folder"],
    ["detect_moves", "settings.detectMoves", "git-branch"],
    ["block_executable_extensions", "settings.blockExec", "alert-triangle"],
    ["allow_registration", "settings.allowReg", "users"],
  ];
  root.append(el("div", { class: "card", style: { marginBottom: "16px" } },
    el("div", { class: "card-header" },
      svgPath("settings", 16), el("h2", null, t("settings.toggles"))),
    el("div", { class: "card-body", style: { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: "8px 24px" } },
      toggles.map(([key, label, iconName]) =>
        el("div", { class: "row", style: { padding: "8px 0", justifyContent: "space-between" } },
          el("div", { class: "row" }, svgPath(iconName, 16), el("span", null, t(label))),
          field(key, "", "toggle")
        )
      )
    )
  ));

  root.append(el("div", { class: "row", style: { justifyContent: "flex-end" } },
    el("button", {
      class: "btn primary lg", type: "button",
      on: { click: async () => {
        try {
          const res = await api("POST", "/api/config", draft);
          toast(t("settings.saved") + (res.restart_required ? " — " + t("settings.restartRequired") : ""), "success");
          render();
        } catch (e) {
          if (e.message !== "unauthorized") toast(e.message, "error");
        }
      } }
    }, svgPath("check", 16), el("span", null, t("common.save")))
  ));

  return root;
}

/* ============================================================
   SHARED RENDER HELPERS
   ============================================================ */
function emptyState(iconName, title, hint) {
  return el("div", { class: "empty" },
    el("div", { class: "empty-icon" }, svgPath(iconName, 28)),
    title ? el("h3", null, title) : null,
    hint ? el("p", null, hint) : null
  );
}

function renderSkeleton(rows) {
  const list = [];
  for (let i = 0; i < (rows || 6); i++) {
    list.push(el("div", { class: "skel-row" },
      el("div", { class: "skel", style: { width: "20px", height: "20px", borderRadius: "4px" } }),
      el("div", { class: "skel skel-line", style: { flex: "1", maxWidth: "240px" } }),
      el("div", { class: "skel skel-line", style: { width: "80px" } }),
      el("div", { class: "skel skel-line", style: { width: "100px" } })
    ));
  }
  return el("div", { class: "card" }, list);
}

/* ============================================================
   NAVIGATION
   ============================================================ */
function navigate(view) {
  if (!NAV_ITEMS.find(i => i.id === view)) view = "files";
  state.view = view;
  location.hash = "#/" + view;
  closeSidebar();
  render();
}

function closeSidebar() {
  const sb = $("#sidebar");
  const bd = $("#sidebarBackdrop");
  if (sb) sb.classList.remove("open");
  if (bd) bd.classList.remove("show");
}

function openSidebar() {
  const sb = $("#sidebar");
  const bd = $("#sidebarBackdrop");
  if (sb) sb.classList.add("open");
  if (bd) bd.classList.add("show");
}

/* ============================================================
   AUTH
   ============================================================ */
async function logout() {
  try { await api("POST", "/api/auth/logout", undefined, { allowUnauth: true }); } catch {}
  state.user = null;
  render();
}

/* ============================================================
   ROOT RENDER
   ============================================================ */
let renderToken = 0;

async function render() {
  const token = ++renderToken;

  // Apply language + theme
  document.documentElement.lang = state.lang;
  document.documentElement.dir = state.lang === "ar" ? "rtl" : "ltr";
  document.documentElement.dataset.theme = state.theme;
  const themeColor = document.querySelector('meta[name="theme-color"]');
  if (themeColor) themeColor.setAttribute("content", state.theme === "dark" ? "#0b0f17" : "#f5f7fb");

  renderSidebar();

  if (!state.user) {
    renderLogin();
    return;
  }

  const app = $("#app");
  if (app) app.style.display = "";

  const actions = el("div", { class: "row" });
  renderTopbar(actions);

  const main = $("#main");
  if (!main) return;

  main.replaceChildren(renderSkeleton(5));

  let content;
  try {
    if (state.view === "files") content = await viewFiles(actions);
    else if (state.view === "peers") content = await viewPeers();
    else if (state.view === "conflicts") content = await viewConflicts();
    else if (state.view === "status") content = await viewStatus(actions);
    else if (state.view === "settings") content = await viewSettings();
    else content = await viewFiles(actions);
  } catch (e) {
    if (e.message !== "unauthorized") {
      content = emptyState("alert-circle", e.message);
    } else {
      return;
    }
  }

  if (token !== renderToken) return;
  main.replaceChildren(content);

  // Update actions after view loaded (some views add their own)
  const title = $("#topbarTitle");
  const actionsHost = $("#topbarActions");
  if (title && actionsHost && state.user) {
    // already rendered
  }
}

function renderLogin() {
  const app = $("#app");
  if (!app) return;
  app.style.display = "none";

  const main = $("#main");
  const topbar = $("#topbar");
  const sidebar = $("#sidebar");
  if (topbar) topbar.style.display = "none";
  if (sidebar) sidebar.style.display = "none";

  const username = el("input", {
    class: "input", type: "text", placeholder: t("login.username"),
    autocomplete: "username", "aria-label": t("login.username"),
    value: ""
  });
  const password = el("input", {
    class: "input", type: "password", placeholder: t("login.password"),
    autocomplete: "current-password", "aria-label": t("login.password")
  });
  const submit = el("button", {
    class: "btn primary lg", type: "submit", style: { width: "100%" }
  }, svgPath("log-out", 16), el("span", null, t("login.submit")));
  const error = el("div", { class: "err small hidden", style: { color: "var(--danger)" } });

  const form = el("form", {
    class: "login-form",
    on: { submit: async (e) => {
      e.preventDefault();
      error.classList.add("hidden");
      submit.disabled = true;
      const original = submit.querySelector("span");
      if (original) original.textContent = t("login.working");
      try {
        const res = await api("POST", "/api/auth/login",
          { username: username.value.trim(), password: password.value },
          { allowUnauth: true });
        state.user = { username: res.user.username, role: res.user.role, local: false };
        showAppChrome();
        await render();
      } catch (err) {
        error.textContent = err.message || t("login.failed");
        error.classList.remove("hidden");
        submit.disabled = false;
        if (original) original.textContent = t("login.submit");
      }
    } }
  }, username, password, error, submit);

  const shell = el("div", { class: "login-shell" },
    el("div", { class: "login-card" },
      el("div", { class: "login-brand" },
        el("div", { class: "brand-mark" },
          (() => {
            const s = document.createElementNS(SVG_NS, "svg");
            s.setAttribute("viewBox", "0 0 24 24");
            s.setAttribute("fill", "none");
            s.setAttribute("stroke", "white");
            s.setAttribute("stroke-width", "2.2");
            s.setAttribute("stroke-linecap", "round");
            const p = document.createElementNS(SVG_NS, "path");
            p.setAttribute("d", "M6 12a6 6 0 0 1 6-6h2M18 12a6 6 0 0 1-6 6h-2");
            s.append(p);
            return s;
          })()
        ),
        el("h1", null, t("login.title")),
        el("p", null, t("login.subtitle"))
      ),
      form
    )
  );

  // Replace main content area entirely, keep sidebar hidden
  const content = $("#loginMount");
  if (content) content.remove();
  const mount = el("div", { id: "loginMount" });
  mount.append(shell);
  document.body.append(mount);
}

function showAppChrome() {
  const mount = $("#loginMount");
  if (mount) mount.remove();
  const app = $("#app");
  const topbar = $("#topbar");
  const sidebar = $("#sidebar");
  if (app) app.style.display = "";
  if (topbar) topbar.style.display = "";
  if (sidebar) sidebar.style.display = "";
}

/* ============================================================
   BOOT
   ============================================================ */
async function boot() {
  // Apply theme early to avoid flash
  document.documentElement.dataset.theme = state.theme;
  document.documentElement.lang = state.lang;
  document.documentElement.dir = state.lang === "ar" ? "rtl" : "ltr";

  // Wire static handlers
  const themeBtn = $("#themeBtn");
  if (themeBtn) themeBtn.addEventListener("click", () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    localStorage.setItem("ss.theme", state.theme);
    render();
  });
  const langBtn = $("#langBtn");
  if (langBtn) langBtn.addEventListener("click", () => {
    state.lang = state.lang === "ar" ? "en" : "ar";
    localStorage.setItem("ss.lang", state.lang);
    render();
  });
  const menuBtn = $("#menuBtn");
  if (menuBtn) {
    menuBtn.replaceChildren(svgPath("menu", 18));
    menuBtn.addEventListener("click", () => {
      const sb = $("#sidebar");
      if (sb.classList.contains("open")) closeSidebar(); else openSidebar();
    });
  }
  const backdrop = $("#sidebarBackdrop");
  if (backdrop) backdrop.addEventListener("click", closeSidebar);

  window.addEventListener("hashchange", () => {
    const v = location.hash.replace(/^#\/?/, "") || "files";
    if (v !== state.view && NAV_ITEMS.find(i => i.id === v)) {
      state.view = v;
      render();
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.target && ["INPUT","TEXTAREA","SELECT"].includes(e.target.tagName)) return;
    if (e.key === "/" && state.view === "files" && state.user) {
      e.preventDefault();
      const si = document.querySelector(".search-input");
      if (si) si.focus();
    } else if (e.key === "Escape") {
      closeSidebar();
    }
  });

  // Drop overlay content
  const dropIcon = $("#dropIcon");
  const dropTitle = $("#dropTitle");
  const dropHint = $("#dropHint");
  if (dropIcon) dropIcon.replaceChildren(svgPath("upload", 40));
  if (dropTitle) dropTitle.textContent = t("files.drop.title");
  if (dropHint) dropHint.textContent = t("files.drop.hint");

  // Global drop handling
  let dragDepth = 0;
  window.addEventListener("dragenter", (e) => {
    if (!state.user) return;
    if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes("Files")) return;
    dragDepth++;
    showDropOverlay(true);
  });
  window.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) showDropOverlay(false);
  });
  window.addEventListener("dragover", (e) => {
    if (!state.user) return;
    if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files")) {
      e.preventDefault();
    }
  });
  window.addEventListener("drop", async (e) => {
    dragDepth = 0;
    showDropOverlay(false);
    if (!state.user) return;
    if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
    e.preventDefault();
    if (state.view !== "files") navigate("files");
    await uploadFiles(Array.from(e.dataTransfer.files));
  });

  // Auth check
  try {
    const me = await api("GET", "/api/auth/me", undefined, { allowUnauth: true });
    state.user = me && me.login_required ? null : me;
  } catch {
    state.user = null;
  }

  // If authenticated, keep the shell visible; otherwise hide
  if (!state.user) {
    const app = $("#app");
    const topbar = $("#topbar");
    const sidebar = $("#sidebar");
    if (app) app.style.display = "none";
    if (topbar) topbar.style.display = "none";
    if (sidebar) sidebar.style.display = "none";
  }

  render();

  // SSE live updates
  try {
    const es = new EventSource("/api/events");
    const refresh = () => { if (state.user) render(); };
    ["file_uploaded", "sync_complete", "conflict_detected", "file_deleted"].forEach(ev => {
      es.addEventListener(ev, refresh);
    });
    es.onerror = () => {};
  } catch {}

  // Slow polling fallback
  setInterval(() => {
    if (!state.user) return;
    if (state.view === "status" || state.view === "peers" || state.view === "conflicts") {
      render();
    }
  }, 20000);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
