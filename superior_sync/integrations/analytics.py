"""Superior Sync integration subsystem."""

from __future__ import annotations

from ._shared import *
from .errors import ErrorCategory, ErrorLevel


class AnalyticsEngine:
    RANGES = {"minute": 60, "hour": 3600, "day": 86400, "week": 604800}
    KINDS = ("system_performance", "network_usage", "sync_operations")

    def __init__(self, data_dir, engine=None, interval=5, config=None, hub=None):
        self.dir = Path(data_dir) / "analytics"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.engine = engine
        self.interval = interval
        self.config = config
        self.hub = hub
        self.metrics = {k: collections.deque(maxlen=20000) for k in self.KINDS}
        self.running = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_net = None
        self._last_alert: dict[str, float] = {}
        if HAS_PSUTIL:
            psutil.cpu_percent(interval=None)
        self._load()
        self.chart_templates = {
            "line": self._line_chart,
            "bar": self._bar_chart,
            "pie": self._pie_chart,
            "scatter": self._scatter_chart,
        }

    def _threshold(self, name: str, default: float) -> float:
        if self.config is None:
            return default
        try:
            return float(getattr(self.config, name, default))
        except (TypeError, ValueError):
            return default

    def _load(self) -> None:
        data = read_json(self.dir / "metrics.json", {}) or {}
        cutoff = time.time() - self.RANGES["week"]
        for kind in self.KINDS:
            for sample in data.get(kind, []):
                if isinstance(sample, dict) and sample.get("timestamp", 0) > cutoff:
                    self.metrics[kind].append(sample)

    def _save(self) -> None:
        try:
            atomic_write_json(
                self.dir / "metrics.json",
                {k: list(v)[-5000:] for k, v in self.metrics.items()},
            )
        except OSError as exc:
            log.debug("حفظ المقاييس: %s", exc)

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="analytics")
        self._thread.start()

    def stop(self) -> None:
        self.running = False
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._save()

    def _loop(self) -> None:
        n = 0
        while not self._stop.wait(self.interval):
            try:
                self.collect()
                self._check_thresholds()
                n += 1
                if n % 60 == 0:
                    self._save()
            except Exception as exc:
                if self.hub is not None:
                    self.hub.report(exc, "فشل جمع المقاييس",
                                    category=ErrorCategory.ANALYTICS)
                else:
                    log.debug("جمع المقاييس: %s", exc)

    def system_snapshot(self) -> dict:
        snap = {
            "timestamp": time.time(),
            "cpu_percent": None, "memory_percent": None,
            "memory_used": None, "memory_total": None,
            "disk_percent": None, "disk_used": None, "disk_total": None,
            "disk_free": None, "process_count": None,
        }
        root = os.path.abspath(os.sep)
        try:
            du = shutil.disk_usage(root)
            snap.update(
                disk_used=du.used, disk_total=du.total, disk_free=du.free,
                disk_percent=round(du.used / du.total * 100, 1),
            )
        except OSError:
            pass
        if HAS_PSUTIL:
            vm = psutil.virtual_memory()
            snap.update(
                cpu_percent=psutil.cpu_percent(interval=None),
                memory_percent=vm.percent,
                memory_used=vm.used, memory_total=vm.total,
                process_count=len(psutil.pids()),
            )
        elif hasattr(os, "getloadavg"):
            with contextlib.suppress(OSError):
                snap["cpu_percent"] = round(
                    min(100.0, os.getloadavg()[0] / (os.cpu_count() or 1) * 100), 1
                )
        return snap

    def network_snapshot(self) -> dict | None:
        if not HAS_PSUTIL:
            return None
        n = psutil.net_io_counters()
        return {
            "timestamp": time.time(),
            "bytes_sent": n.bytes_sent, "bytes_recv": n.bytes_recv,
            "packets_sent": n.packets_sent, "packets_recv": n.packets_recv,
            "error_in": n.errin, "error_out": n.errout,
        }

    def collect(self) -> None:
        self.metrics["system_performance"].append(self.system_snapshot())
        net = self.network_snapshot()
        if net:
            if self._last_net:
                dt = max(net["timestamp"] - self._last_net["timestamp"], 1e-6)
                net["send_rate"] = max(0, (net["bytes_sent"] - self._last_net["bytes_sent"]) / dt)
                net["recv_rate"] = max(0, (net["bytes_recv"] - self._last_net["bytes_recv"]) / dt)
            self._last_net = net
            self.metrics["network_usage"].append(net)
        if self.engine:
            s = self.engine.get_stats()
            self.metrics["sync_operations"].append({
                "timestamp": time.time(),
                "files_pulled": s["transfer"]["files_pulled"],
                "bytes_sent": s["transfer"]["bytes_sent"],
                "bytes_received": s["transfer"]["bytes_received"],
                "peers_online": s["p2p_protocol"]["peers_online"],
                "conflicts": s["transfer"]["conflicts"],
            })

    def _check_thresholds(self) -> None:
        if self.hub is None or not self.metrics["system_performance"]:
            return
        snap = self.metrics["system_performance"][-1]
        cpu_limit = self._threshold("cpu_high_threshold", 90.0)
        mem_limit = self._threshold("memory_high_threshold", 90.0)
        disk_limit_mb = self._threshold("disk_low_threshold_mb", 500.0)
        for key, value, limit, label in (
            ("cpu", snap.get("cpu_percent"), cpu_limit, "المعالج"),
            ("memory", snap.get("memory_percent"), mem_limit, "الذاكرة"),
        ):
            if value is None or value < limit:
                continue
            self._maybe_alert(
                key,
                level=ErrorLevel.WARNING,
                category=ErrorCategory.ANALYTICS,
                title=f"استهلاك {label} مرتفع",
                message=f"{label}: {value:.1f}% (الحد: {limit:.0f}%)",
                cooldown=600,
            )
        free = snap.get("disk_free")
        if free is not None and free < disk_limit_mb * 1024 * 1024:
            self._maybe_alert(
                "disk",
                level=ErrorLevel.ERROR,
                category=ErrorCategory.STORAGE,
                title="مساحة القرص منخفضة",
                message=f"المتاح: {human_size(free)} (الحد: {disk_limit_mb:.0f} MB)",
                cooldown=900,
            )

    def _maybe_alert(self, key: str, *, level, category, title, message, cooldown: float) -> None:
        now = time.time()
        if now - self._last_alert.get(key, 0) < cooldown:
            return
        self._last_alert[key] = now
        if self.hub is not None:
            self.hub.alert(title, message, level=level, category=category)

    def get_metrics(self, metric_type: str, time_range: str = "hour") -> list[dict]:
        if metric_type not in self.metrics:
            return []
        cutoff = time.time() - self.RANGES.get(time_range, 3600)
        return [m for m in self.metrics[metric_type] if m["timestamp"] >= cutoff]

    def health_score(self) -> dict:
        """درجة صحّة موحّدة من 0 إلى 100 مع تفصيل المصادر."""
        snapshot = self.system_snapshot()
        score = 100.0
        factors: list[dict] = []

        def penalize(name: str, amount: float, detail: str) -> None:
            nonlocal score
            amount = max(0.0, min(100.0, amount))
            score -= amount
            factors.append({"factor": name, "penalty": round(amount, 1), "detail": detail})

        cpu = snapshot.get("cpu_percent")
        if cpu is not None and cpu > 75:
            penalize("cpu", (cpu - 75) * 0.6, f"CPU {cpu:.0f}%")
        mem = snapshot.get("memory_percent")
        if mem is not None and mem > 75:
            penalize("memory", (mem - 75) * 0.6, f"RAM {mem:.0f}%")
        disk = snapshot.get("disk_percent")
        if disk is not None and disk > 85:
            penalize("disk", (disk - 85) * 1.2, f"Disk {disk:.0f}%")

        if self.hub is not None:
            err_stats = self.hub.errors.stats()
            recent = err_stats.get("recent_5m", 0)
            if recent > 5:
                penalize("errors", min(25.0, recent * 1.5),
                         f"{recent} أخطاء في آخر 5 دقائق")
            unresolved = err_stats.get("unresolved", 0)
            if unresolved > 0:
                penalize("unresolved", min(15.0, unresolved * 0.5),
                         f"{unresolved} خطأ غير محلول")

        if self.engine is not None:
            try:
                st = self.engine.get_stats()
                conflicts = st["transfer"].get("conflicts", 0)
                if conflicts > 10:
                    penalize("conflicts", min(15.0, conflicts * 0.3),
                             f"{conflicts} تعارض قائم")
            except Exception:
                pass

        score = max(0.0, min(100.0, score))
        if score >= 85:
            grade = "excellent"
        elif score >= 70:
            grade = "good"
        elif score >= 50:
            grade = "fair"
        elif score >= 25:
            grade = "poor"
        else:
            grade = "critical"

        return {"score": round(score, 1), "grade": grade,
                "factors": factors, "snapshot": snapshot}

    @staticmethod
    def _esc(s) -> str:
        return (str(s).replace("&", "&amp;")
                .replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;"))

    def generate_chart(self, chart_type: str, data, options=None) -> str:
        fn = self.chart_templates.get(chart_type)
        if not fn:
            raise ValueError("نوع رسم غير مدعوم")
        return fn(data, options or {})

    def _frame(self, w, h, title):
        return [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {w} {h}" width="100%" role="img" '
            f'font-family="Segoe UI,Tahoma,sans-serif" '
            f'font-size="12"><title>{self._esc(title)}</title>',
            f'<text x="{w/2}" y="20" text-anchor="middle" '
            f'font-size="14" font-weight="600" fill="currentColor">'
            f'{self._esc(title)}</text>',
        ]

    def _axes(self, out, w, h, pad, ymin, ymax, ticks=5):
        for i in range(ticks + 1):
            y = pad["t"] + (h - pad["t"] - pad["b"]) * i / ticks
            v = ymax - (ymax - ymin) * i / ticks
            out.append(
                f'<line x1="{pad["l"]}" y1="{y:.1f}" '
                f'x2="{w-pad["r"]}" y2="{y:.1f}" '
                f'stroke="currentColor" opacity=".15"/>'
            )
            out.append(
                f'<text x="{pad["l"]-6}" y="{y+4:.1f}" '
                f'text-anchor="end" fill="currentColor" '
                f'opacity=".7">{v:.3g}</text>'
            )

    def _line_chart(self, data, o):
        pts = [(float(x), float(y)) for x, y in data if y is not None]
        w = o.get("width", 640)
        h = o.get("height", 260)
        pad = {"l": 50, "r": 16, "t": 34, "b": 28}
        out = self._frame(w, h, o.get("title", ""))
        if len(pts) < 2:
            out.append(
                f'<text x="{w/2}" y="{h/2}" text-anchor="middle" '
                f'fill="currentColor" opacity=".6">'
                f'لا توجد بيانات كافية</text></svg>'
            )
            return "".join(out)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        ymin, ymax = min(0, min(ys)), max(ys) or 1
        if ymax == ymin:
            ymax = ymin + 1
        xmin, xmax = min(xs), max(xs)
        sx = lambda x: pad["l"] + (x - xmin) / ((xmax - xmin) or 1) * (w - pad["l"] - pad["r"])
        sy = lambda y: h - pad["b"] - (y - ymin) / ((ymax - ymin) or 1) * (h - pad["t"] - pad["b"])
        self._axes(out, w, h, pad, ymin, ymax)
        path = " ".join(f'{"M" if i == 0 else "L"}{sx(x):.1f},{sy(y):.1f}'
                        for i, (x, y) in enumerate(pts))
        color = o.get("color", "#2563eb")
        out.append(
            f'<path d="{path} L{sx(xmax):.1f},{h-pad["b"]} '
            f'L{sx(xmin):.1f},{h-pad["b"]} Z" fill="{color}" opacity=".12"/>'
        )
        out.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2"/></svg>')
        return "".join(out)

    def _bar_chart(self, data, o):
        items = [(str(k), float(v)) for k, v in data]
        w = o.get("width", 640)
        h = o.get("height", 260)
        pad = {"l": 50, "r": 16, "t": 34, "b": 40}
        out = self._frame(w, h, o.get("title", ""))
        if not items:
            out.append(
                f'<text x="{w/2}" y="{h/2}" text-anchor="middle" '
                f'fill="currentColor" opacity=".6">'
                f'لا توجد بيانات</text></svg>'
            )
            return "".join(out)
        ymax = max(v for _, v in items) or 1
        self._axes(out, w, h, pad, 0, ymax)
        bw = (w - pad["l"] - pad["r"]) / len(items)
        for i, (k, v) in enumerate(items):
            bh = v / ymax * (h - pad["t"] - pad["b"])
            x = pad["l"] + i * bw + bw * 0.15
            out.append(
                f'<rect x="{x:.1f}" y="{h-pad["b"]-bh:.1f}" '
                f'width="{bw*0.7:.1f}" height="{bh:.1f}" rx="3" '
                f'fill="{o.get("color", "#10b981")}"/>'
            )
            out.append(
                f'<text x="{x+bw*0.35:.1f}" y="{h-pad["b"]+16}" '
                f'text-anchor="middle" fill="currentColor" '
                f'opacity=".8">{self._esc(k[:12])}</text>'
            )
        out.append("</svg>")
        return "".join(out)

    def _pie_chart(self, data, o):
        items = [(str(k), float(v)) for k, v in data if float(v) > 0]
        w, h = o.get("width", 420), o.get("height", 260)
        out = self._frame(w, h, o.get("title", ""))
        total = sum(v for _, v in items)
        if not total:
            out.append(
                f'<text x="{w/2}" y="{h/2}" text-anchor="middle" '
                f'fill="currentColor" opacity=".6">'
                f'لا توجد بيانات</text></svg>'
            )
            return "".join(out)
        palette = ["#2563eb", "#10b981", "#f59e0b", "#ef4444",
                   "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16"]
        cx, cy, r, a0 = 120, h / 2 + 12, 88, -math.pi / 2
        for i, (k, v) in enumerate(items):
            a1 = a0 + v / total * 2 * math.pi
            col = palette[i % len(palette)]
            if len(items) == 1:
                out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{col}"/>')
            else:
                x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
                x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
                out.append(
                    f'<path d="M{cx},{cy} L{x0:.1f},{y0:.1f} '
                    f'A{r},{r} 0 {1 if a1-a0 > math.pi else 0} 1 '
                    f'{x1:.1f},{y1:.1f} Z" fill="{col}"/>'
                )
            out.append(
                f'<rect x="240" y="{50+i*22}" width="12" height="12" rx="2" fill="{col}"/>'
                f'<text x="258" y="{61+i*22}" fill="currentColor">'
                f'{self._esc(k[:20])} — {v/total:.0%}</text>'
            )
            a0 = a1
        out.append("</svg>")
        return "".join(out)

    def _scatter_chart(self, data, o):
        pts = [(float(x), float(y)) for x, y in data]
        w = o.get("width", 640)
        h = o.get("height", 260)
        pad = {"l": 50, "r": 16, "t": 34, "b": 28}
        out = self._frame(w, h, o.get("title", ""))
        if not pts:
            out.append(
                f'<text x="{w/2}" y="{h/2}" text-anchor="middle" '
                f'fill="currentColor" opacity=".6">'
                f'لا توجد بيانات</text></svg>'
            )
            return "".join(out)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(0, min(ys)), max(ys) or 1
        if ymax == ymin:
            ymax = ymin + 1
        if xmax == xmin:
            xmax = xmin + 1
        self._axes(out, w, h, pad, ymin, ymax)
        for x, y in pts:
            px = pad["l"] + (x - xmin) / ((xmax - xmin) or 1) * (w - pad["l"] - pad["r"])
            py = h - pad["b"] - (y - ymin) / ((ymax - ymin) or 1) * (h - pad["t"] - pad["b"])
            out.append(
                f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" '
                f'fill="{o.get("color", "#8b5cf6")}" opacity=".75"/>'
            )
        out.append("</svg>")
        return "".join(out)

    def get_dashboard_data(self, time_range: str = "hour") -> dict:
        sysm = self.get_metrics("system_performance", time_range)
        net = self.get_metrics("network_usage", time_range)
        cur = sysm[-1] if sysm else self.system_snapshot()

        def series(rows, key):
            return [(r["timestamp"], r.get(key)) for r in rows if r.get(key) is not None]

        charts = {
            "cpu": self.generate_chart("line", series(sysm, "cpu_percent"),
                                       {"title": "المعالج %", "color": "#ef4444"}),
            "memory": self.generate_chart("line", series(sysm, "memory_percent"),
                                          {"title": "الذاكرة %", "color": "#8b5cf6"}),
            "recv": self.generate_chart("line", series(net, "recv_rate"),
                                        {"title": "الاستقبال (بايت/ث)", "color": "#10b981"}),
            "send": self.generate_chart("line", series(net, "send_rate"),
                                        {"title": "الإرسال (بايت/ث)", "color": "#2563eb"}),
        }
        if cur.get("disk_total"):
            charts["disk"] = self.generate_chart(
                "pie",
                [("مستخدم", cur["disk_used"]),
                 ("متاح", cur["disk_total"] - cur["disk_used"])],
                {"title": "القرص"},
            )
        return {
            "current": cur,
            "charts": charts,
            "psutil": HAS_PSUTIL,
            "samples": len(sysm),
            "health": self.health_score(),
        }


# ==================================================================
# الإشعارات — إجراءات، أولويات، تجميع، SSE
# ==================================================================
