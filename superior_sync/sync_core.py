from __future__ import annotations

import collections
import contextlib
import datetime
import gc
import hashlib
import heapq
import http.client
import itertools
import json
import math
import os
import shutil
import struct
import threading
import time
import traceback
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import i18n
from .config import Database, validate_sync_folder
from .network import FrameCodec, P2PProtocol, PeerClient, PeerError
from .utils import (
    FileWatcher,
    MAX_HASH_SIZE_BYTES,
    PathError,
    file_hash,
    human_size,
    is_ignored,
    log,
    safe_join,
    sanitize_relpath,
    unique_path,
)

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None
    HAS_PSUTIL = False


class DeltaSync:
    MIN_BLOCK = 16 * 1024
    MAX_BLOCK = 1024 * 1024
    LITERAL_FLUSH = 1024 * 1024
    READ_CHUNK = 4 * 1024 * 1024
    ROLLING_LIMIT = 1024 * 1024 * 1024
    # [PERF] إذا لم تتطابق أي كتلة بعد مسح هذا القدر بالبحث التدحرجي (≈1.4MB/s في
    # بايثون) نتحول إلى مقارنة محاذية للكتل فقط. الناتج يبقى صحيحًا بالبايت، وإنما
    # قد نفقد إعادة استخدام كتل مزاحة؛ مقابل سرعة أكبر بمرتبة للملفات المعاد ترميزها كليًا.
    ROLL_PROBE_BYTES = 4 * 1024 * 1024
    ROLL_RECOMPUTE_EVERY = 8192
    CACHE_LIMIT = 32
    CACHE_MAX_SIZE = 64 * 1024 * 1024

    def __init__(self):
        self.stats = {
            "blocks_reused": 0,
            "bytes_saved": 0,
            "sync_operations": 0,
            "bytes_transferred": 0,
        }
        self._lock = threading.Lock()
        self._sig_lock = threading.RLock()
        self._sig_cache = collections.OrderedDict()

    def _bump(self, **values):
        with self._lock:
            for key, value in values.items():
                self.stats[key] = self.stats.get(key, 0) + value

    @classmethod
    def block_size_for(cls, size):
        if size <= cls.MIN_BLOCK:
            return cls.MIN_BLOCK
        scaled = max(1.0, math.sqrt(float(size)))
        block = 1 << (int(scaled).bit_length() - 1)
        return max(cls.MIN_BLOCK, min(cls.MAX_BLOCK, block))

    @staticmethod
    def _strong(data):
        return hashlib.blake2b(data, digest_size=16).hexdigest()

    @staticmethod
    def _weak(data):
        if not data:
            return 0, 0
        a = sum(data) & 0xFFFF
        b = sum(itertools.accumulate(data)) & 0xFFFF
        return a, b

    def _cache_key(self, path):
        try:
            st = os.stat(path)
        except OSError:
            return None
        return os.path.abspath(path), st.st_size, st.st_mtime_ns

    def _signature_uncached(self, path, size, block_size):
        if size > MAX_HASH_SIZE_BYTES:
            raise ValueError(
                f"file exceeds the {MAX_HASH_SIZE_BYTES}-byte signature limit"
            )
        blocks = []
        with open(path, "rb", buffering=0) as fh:
            remaining = size
            while remaining:
                data = fh.read(min(block_size, remaining))
                if not data:
                    raise OSError("الملف تغير أثناء بناء التوقيع")
                a, b = self._weak(data)
                blocks.append(((b << 16) | a, self._strong(data)))
                remaining -= len(data)
        return {
            "block_size": block_size,
            "size": size,
            "blocks": blocks,
        }

    def signature(self, path):
        key = self._cache_key(path)
        if key is None:
            raise FileNotFoundError(path)
        with self._sig_lock:
            cached = self._sig_cache.get(key)
            if cached is not None:
                self._sig_cache.move_to_end(key)
                return {
                    "block_size": cached["block_size"],
                    "size": cached["size"],
                    "blocks": list(cached["blocks"]),
                }
        _, size, _ = key
        block_size = self.block_size_for(size)
        result = self._signature_uncached(path, size, block_size)
        if size <= self.CACHE_MAX_SIZE:
            with self._sig_lock:
                self._sig_cache[key] = result
                self._sig_cache.move_to_end(key)
                while len(self._sig_cache) > self.CACHE_LIMIT:
                    self._sig_cache.popitem(last=False)
        return {
            "block_size": result["block_size"],
            "size": result["size"],
            "blocks": list(result["blocks"]),
        }

    def invalidate(self, path):
        absolute = os.path.abspath(path)
        with self._sig_lock:
            for key in tuple(self._sig_cache):
                if key[0] == absolute:
                    self._sig_cache.pop(key, None)

    def iter_delta(self, path, sig=None):
        try:
            size = os.path.getsize(path)
        except OSError:
            yield ("error", "الملف غير موجود")
            return
        whole = hashlib.blake2b(digest_size=32)
        if not sig or not sig.get("blocks"):
            with open(path, "rb", buffering=0) as fh:
                for chunk in iter(lambda: fh.read(self.READ_CHUNK), b""):
                    whole.update(chunk)
                    yield ("data", chunk)
            yield ("end", whole.hexdigest(), size)
            return

        try:
            block_size = int(sig["block_size"])
            old_size = int(sig["size"])
            blocks = sig["blocks"]
            if block_size <= 0 or old_size < 0 or not isinstance(blocks, list):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            yield from self.iter_delta(path, None)
            return

        block_count = len(blocks)
        expected_old = block_size * max(0, block_count - 1)
        tail_len = old_size - expected_old
        if block_count == 1:
            tail_len = old_size
        if tail_len <= 0 or tail_len > block_size:
            yield from self.iter_delta(path, None)
            return

        weak_map = {}
        for index, pair in enumerate(blocks):
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            weak_map.setdefault(int(pair[0]), []).append((index, pair[1]))

        tail_sig = blocks[-1] if tail_len != block_size else None
        rolling = size <= self.ROLLING_LIMIT and block_size <= self.MAX_BLOCK
        literal = bytearray()
        buffer = bytearray()
        pos = 0
        eof = False
        weak_a = weak_b = 0
        have_weak = False
        rolls = 0
        reused = 0
        saved = 0
        rolled_total = 0
        probe_limit = max(self.ROLL_PROBE_BYTES, 4 * block_size)

        with open(path, "rb", buffering=0) as fh:
            while True:
                available = len(buffer) - pos
                if available <= block_size and not eof:
                    if pos:
                        del buffer[:pos]
                        pos = 0
                    chunk = fh.read(self.READ_CHUNK)
                    if chunk:
                        whole.update(chunk)
                        buffer.extend(chunk)
                    else:
                        eof = True
                    have_weak = False
                    rolls = 0
                    continue

                available = len(buffer) - pos
                if not available:
                    break

                if available < block_size:
                    tail = bytes(buffer[pos:])
                    if tail_sig is not None and len(tail) == tail_len:
                        a, b = self._weak(tail)
                        if ((b << 16) | a) == int(tail_sig[0]) and self._strong(tail) == tail_sig[1]:
                            if literal:
                                yield ("data", bytes(literal))
                                literal.clear()
                            reused += 1
                            saved += len(tail)
                            yield ("copy", block_count - 1)
                            pos += len(tail)
                            break
                    literal.extend(tail)
                    pos = len(buffer)
                    break

                if not have_weak:
                    a, b = self._weak(memoryview(buffer)[pos:pos + block_size])
                    weak_a, weak_b = a, b
                    have_weak = True
                    rolls = 0

                weak_value = (weak_b << 16) | weak_a
                candidates = weak_map.get(weak_value)
                matched = False
                if candidates:
                    window = memoryview(buffer)[pos:pos + block_size]
                    strong = self._strong(window)
                    window.release()
                    for index, expected in candidates:
                        if strong == expected:
                            if literal:
                                yield ("data", bytes(literal))
                                literal.clear()
                            reused += 1
                            saved += block_size
                            yield ("copy", index)
                            pos += block_size
                            have_weak = False
                            rolls = 0
                            matched = True
                            break
                if matched:
                    continue

                if not rolling:
                    literal.extend(buffer[pos:pos + block_size])
                    pos += block_size
                    have_weak = False
                    rolls = 0
                else:
                    outgoing = buffer[pos]
                    incoming_index = pos + block_size
                    if incoming_index < len(buffer):
                        incoming = buffer[incoming_index]
                        weak_a = (weak_a - outgoing + incoming) & 0xFFFF
                        weak_b = (weak_b - block_size * outgoing + weak_a) & 0xFFFF
                        rolls += 1
                        if rolls >= self.ROLL_RECOMPUTE_EVERY:
                            have_weak = False
                            rolls = 0
                    else:
                        have_weak = False
                        rolls = 0
                    literal.append(outgoing)
                    pos += 1
                    rolled_total += 1
                    if rolled_total >= probe_limit and not reused:
                        rolling = False
                        have_weak = False
                        rolls = 0

                if len(literal) >= self.LITERAL_FLUSH:
                    yield ("data", bytes(literal))
                    literal.clear()

        if literal:
            yield ("data", bytes(literal))
        if reused or saved:
            self._bump(blocks_reused=reused, bytes_saved=saved)
        yield ("end", whole.hexdigest(), size)

    @staticmethod
    def apply(ops, out_path, basis_path=None, basis_sig=None):
        block_size = int(basis_sig["block_size"]) if basis_sig else 0
        basis_size = int(basis_sig["size"]) if basis_sig else 0
        digest = hashlib.blake2b(digest_size=32)
        written = 0
        sent = 0
        end = None
        basis = None
        if basis_path and basis_sig and basis_sig.get("blocks"):
            basis = open(basis_path, "rb", buffering=0)
        try:
            with open(out_path, "wb", buffering=0) as out:
                for op in ops:
                    if not op:
                        continue
                    kind = op[0]
                    if kind == "data":
                        data = op[1]
                        out.write(data)
                        digest.update(data)
                        size = len(data)
                        written += size
                        sent += size
                    elif kind == "copy":
                        if basis is None:
                            raise ValueError("أمر نسخ بدون ملف أساس")
                        index = int(op[1])
                        offset = index * block_size
                        if offset < 0 or offset >= basis_size:
                            raise ValueError("كتلة أساس غير صالحة")
                        basis.seek(offset)
                        data = basis.read(min(block_size, basis_size - offset))
                        if not data:
                            raise IOError("تعذر قراءة كتلة الأساس")
                        out.write(data)
                        digest.update(data)
                        written += len(data)
                    elif kind == "end":
                        end = op
                        break
                    elif kind == "error":
                        raise IOError(f"خطأ من النظير: {op[1]}")
                    elif kind == "meta":
                        continue
                    else:
                        raise ValueError(f"أمر غير معروف: {kind}")
                out.flush()
                os.fsync(out.fileno())
        finally:
            if basis is not None:
                basis.close()
        if end is None:
            raise IOError("انتهى البث قبل اكتمال الملف")
        if digest.hexdigest() != end[1] or written != int(end[2]):
            raise IOError("فشل التحقق من سلامة الملف بعد التطبيق")
        return end[1], written, sent

    @staticmethod
    def encode_op(op):
        kind = op[0]
        if kind == "copy":
            return b"C" + struct.pack(">I", int(op[1]))
        if kind == "data":
            return b"D" + op[1]
        if kind == "end":
            return b"E" + bytes.fromhex(op[1]) + struct.pack(">Q", int(op[2]))
        if kind == "error":
            return b"X" + str(op[1]).encode("utf-8", "replace")
        if kind == "meta":
            return b"H" + json.dumps(op[1], separators=(",", ":")).encode("utf-8")
        raise ValueError(kind)

    @staticmethod
    def decode_op(data):
        if not data:
            raise ValueError("أمر فارغ")
        kind, body = data[:1], data[1:]
        if kind == b"C":
            if len(body) != 4:
                raise ValueError("أمر نسخ غير صالح")
            return ("copy", struct.unpack(">I", body)[0])
        if kind == b"D":
            return ("data", body)
        if kind == b"E":
            if len(body) != 40:
                raise ValueError("أمر نهاية غير صالح")
            return ("end", body[:32].hex(), struct.unpack(">Q", body[32:40])[0])
        if kind == b"X":
            return ("error", body.decode("utf-8", "replace"))
        if kind == b"H":
            return ("meta", json.loads(body.decode("utf-8")))
        raise ValueError("أمر غير معروف")

    def get_stats(self):
        with self._lock:
            return dict(self.stats)


class TaskQueue:
    PRIORITIES = {"high": 0, "normal": 1, "low": 2}

    def __init__(self, max_workers=8, max_memory_mb=1024):
        self.max_workers = max(1, int(max_workers))
        self.allowed_workers = self.max_workers
        self.max_memory_bytes = max(64, int(max_memory_mb)) * 1024 * 1024
        self.memory_warning_threshold = 0.85
        self.running = False
        self._cond = threading.Condition()
        self._heap = []
        self._seq = itertools.count()
        self._keys = set()
        self._cancelled = set()
        self._workers = []
        self._active = {}
        self._monitor = None
        self.current_memory_usage = 0
        self._retry_timers = set()
        self.stats = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "tasks_queued": 0,
            "tasks_cancelled": 0,
            "memory_warnings": 0,
        }

    def start(self):
        with self._cond:
            if self.running:
                return
            self.running = True
            self.allowed_workers = self.max_workers
        self._workers = []
        for wid in range(self.max_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                args=(wid,),
                daemon=True,
                name=f"Worker-{wid}",
            )
            worker.start()
            self._workers.append(worker)
        self._monitor = threading.Thread(
            target=self._memory_loop,
            daemon=True,
            name="MemMonitor",
        )
        self._monitor.start()

    def stop(self):
        with self._cond:
            if not self.running and not self._workers:
                return
            self.running = False
            self._cond.notify_all()
            timers = tuple(self._retry_timers)
            self._retry_timers.clear()
        for timer in timers:
            with contextlib.suppress(Exception):
                timer.cancel()
        for worker in self._workers:
            worker.join(timeout=3)
        self._workers = []
        if self._monitor is not None:
            self._monitor.join(timeout=1)
            self._monitor = None
        with self._cond:
            self._heap.clear()
            self._keys.clear()
            self._cancelled.clear()
            self._active.clear()
            self._cond.notify_all()

    def add_task(self, task, priority="normal"):
        task = dict(task)
        task_id = task.setdefault("id", uuid.uuid4().hex)
        priority = priority if priority in self.PRIORITIES else "normal"
        task["_priority"] = priority
        key = task.get("key")
        with self._cond:
            if key is not None and key in self._keys:
                return None
            if key is not None:
                self._keys.add(key)
            heapq.heappush(self._heap, (self.PRIORITIES[priority], next(self._seq), task))
            self.stats["tasks_queued"] += 1
            self._cond.notify()
        return task_id

    def cancel_task(self, task_id):
        with self._cond:
            found = any(task.get("id") == task_id for _, _, task in self._heap)
            if not found:
                return False
            self._cancelled.add(task_id)
            self._cond.notify_all()
            return True

    def wait_for_completion(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while self._heap or self._active:
                if deadline is None:
                    wait_for = 0.5
                else:
                    wait_for = deadline - time.monotonic()
                    if wait_for <= 0:
                        return False
                    wait_for = min(0.5, wait_for)
                self._cond.wait(wait_for)
        return True

    def _worker_loop(self, worker_id):
        while True:
            cancelled_callback = None
            task = None
            with self._cond:
                while self.running and (not self._heap or len(self._active) >= self.allowed_workers):
                    self._cond.wait(0.5)
                if not self.running:
                    return
                _, _, task = heapq.heappop(self._heap)
                key = task.get("key")
                if key is not None:
                    self._keys.discard(key)
                if task["id"] in self._cancelled:
                    self._cancelled.discard(task["id"])
                    self.stats["tasks_cancelled"] += 1
                    cancelled_callback = task.get("on_cancel")
                    self._cond.notify_all()
                    task = None
                else:
                    self._active[task["id"]] = {
                        "worker": worker_id,
                        "start": time.time(),
                        "type": task.get("type", "task"),
                    }
            if task is None:
                self._call(cancelled_callback)
                continue
            try:
                self._run(task)
            finally:
                with self._cond:
                    self._active.pop(task["id"], None)
                    self._cond.notify_all()

    @staticmethod
    def _call(fn, *args):
        if not callable(fn):
            return
        try:
            fn(*args)
        except Exception as exc:
            log.error("خطأ في callback المهمة: %s", exc)

    def _schedule_retry(self, task, priority, delay):
        retry = {k: v for k, v in task.items() if k != "id"}

        def run():
            with self._cond:
                self._retry_timers.discard(timer)
                active = self.running
            if active:
                self.add_task(retry, priority)

        timer = threading.Timer(delay, run)
        timer.daemon = True
        with self._cond:
            self._retry_timers.add(timer)
        timer.start()

    def _run(self, task):
        fn = task.get("function")
        try:
            if not callable(fn):
                raise ValueError("دالة المهمة غير قابلة للاستدعاء")
            result = fn(*task.get("args", ()), **task.get("kwargs", {}))
        except Exception as exc:
            attempt = int(task.get("retry_count", 0))
            max_retries = int(task.get("max_retries", 0))
            if attempt < max_retries:
                task["retry_count"] = attempt + 1
                delay = min(60, max(1, 2 ** min(attempt, 5)))
                self._schedule_retry(task, task.get("_priority", "normal"), delay)
                return
            with self._cond:
                self.stats["tasks_failed"] += 1
            log.error("فشلت المهمة %s: %s", task.get("type"), exc)
            log.debug("%s", traceback.format_exc())
            self._call(task.get("on_error"), exc)
            return
        with self._cond:
            self.stats["tasks_completed"] += 1
        self._call(task.get("on_success"), result)

    def _memory_loop(self):
        low_threshold = self.memory_warning_threshold * 0.7
        while self.running:
            try:
                if HAS_PSUTIL:
                    usage = psutil.Process(os.getpid()).memory_info().rss
                    self.current_memory_usage = usage
                    ratio = usage / self.max_memory_bytes
                    if ratio >= self.memory_warning_threshold:
                        with self._cond:
                            self.stats["memory_warnings"] += 1
                            self.allowed_workers = max(1, self.allowed_workers - 1)
                        gc.collect()
                    elif ratio < low_threshold:
                        with self._cond:
                            if self.allowed_workers < self.max_workers:
                                self.allowed_workers += 1
                                self._cond.notify_all()
            except Exception as exc:
                log.debug("مراقبة الذاكرة: %s", exc)
            if not self.running:
                break
            time.sleep(5)

    def get_stats(self):
        with self._cond:
            result = dict(self.stats)
            result["active_tasks"] = len(self._active)
            result["queued"] = len(self._heap)
            result["workers_allowed"] = self.allowed_workers
        result["memory_usage_mb"] = round(self.current_memory_usage / (1024 * 1024), 1)
        return result


class ConflictResolver:
    def __init__(self, db, data_dir, config):
        self.db = db
        self.config = config
        self.version_dir = Path(data_dir) / "versions"
        self.trash_dir = Path(data_dir) / "trash"
        self.version_dir.mkdir(parents=True, exist_ok=True)
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        self.conflict_strategies = ("newer", "older", "larger", "source", "target", "ask")

    def decide(self, strategy, local, remote, local_node, remote_node):
        def key(meta, field):
            return (
                meta.get(field) or 0,
                meta.get("mtime_ns") or 0,
                meta.get("hash") or "",
            )
        if strategy == "older":
            local_key = (-(local.get("mtime_ns") or 0), local.get("hash") or "")
            remote_key = (-(remote.get("mtime_ns") or 0), remote.get("hash") or "")
        elif strategy == "larger":
            local_key, remote_key = key(local, "size"), key(remote, "size")
        elif strategy == "source":
            return "local" if local_node < remote_node else "remote"
        elif strategy == "target":
            return "local" if local_node > remote_node else "remote"
        else:
            local_key = (local.get("mtime_ns") or 0, local.get("hash") or "")
            remote_key = (remote.get("mtime_ns") or 0, remote.get("hash") or "")
        return "local" if local_key >= remote_key else "remote"

    def record_conflict(
        self,
        share,
        path,
        peer,
        strategy,
        winner,
        local_hash,
        remote_hash,
        needs_review,
        copy_path=None,
        info=None,
    ):
        existing = self.db.one(
            "SELECT id FROM conflicts WHERE share=? AND path=? AND peer=? AND local_hash=? AND remote_hash=?",
            (share, path, peer, local_hash, remote_hash),
        )
        if existing:
            return existing["id"]
        conflict_id = uuid.uuid4().hex
        self.db.execute(
            "INSERT INTO conflicts(id,share,path,peer,strategy,winner,local_hash,remote_hash,detected_at,resolved,needs_review,copy_path,info) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                conflict_id,
                share,
                path,
                peer,
                strategy,
                winner,
                local_hash,
                remote_hash,
                time.time(),
                0 if needs_review else 1,
                1 if needs_review else 0,
                copy_path,
                json.dumps(info or {}, ensure_ascii=False),
            ),
        )
        return conflict_id

    @property
    def conflicts(self):
        return self.list_conflicts()

    def list_conflicts(self, only_open=False):
        sql = "SELECT * FROM conflicts"
        if only_open:
            sql += " WHERE resolved=0"
        return self.db.query(sql + " ORDER BY detected_at DESC LIMIT 500")

    def resolve_manual(self, conflict_id, action, share_root):
        conflict = self.db.one("SELECT * FROM conflicts WHERE id=?", (conflict_id,))
        if not conflict:
            return False, i18n.t("conflict.not_found")
        if action == "swap":
            if not conflict.get("copy_path"):
                return False, i18n.t("conflict.no_copy")
            main = safe_join(share_root, conflict["path"])
            copy = safe_join(share_root, conflict["copy_path"])
            if not os.path.isfile(copy):
                return False, i18n.t("conflict.copy_missing")
            if os.path.exists(main):
                self.create_version(main, "before_manual_swap")
            os.replace(copy, main)
            now_ns = time.time_ns()
            os.utime(main, ns=(now_ns, now_ns))
        elif action != "accept":
            return False, i18n.t("conflict.unknown_action")
        self.db.execute(
            "UPDATE conflicts SET resolved=1, needs_review=0, resolved_at=?, resolution=? WHERE id=?",
            (time.time(), action, conflict_id),
        )
        return True, None

    def create_version(self, file_path, note=""):
        try:
            if not os.path.isfile(file_path):
                return None
            key = hashlib.sha1(os.path.abspath(file_path).encode()).hexdigest()[:16]
            directory = self.version_dir / key
            directory.mkdir(parents=True, exist_ok=True)
            version_path = directory / (
                f"{datetime.datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
            )
            shutil.copy2(file_path, version_path)
            info = {
                "file_path": os.path.abspath(file_path),
                "version_path": str(version_path),
                "created_at": time.time(),
                "size": os.path.getsize(version_path),
                "hash": file_hash(version_path),
                "note": note,
            }
            info["id"] = self.db.execute(
                "INSERT INTO versions(file_path,version_path,created_at,size,hash,note) VALUES(?,?,?,?,?,?)",
                (
                    info["file_path"],
                    info["version_path"],
                    info["created_at"],
                    info["size"],
                    info["hash"],
                    note,
                ),
            )
            self._prune_versions(info["file_path"])
            return info
        except OSError as exc:
            log.error("فشل إنشاء إصدار: %s", exc)
            return None

    def _prune_versions(self, file_path):
        rows = self.db.query(
            "SELECT id,version_path FROM versions WHERE file_path=? ORDER BY created_at DESC",
            (file_path,),
        )
        keep = max(1, int(self.config.max_versions_per_file))
        for row in rows[keep:]:
            with contextlib.suppress(OSError):
                os.remove(row["version_path"])
            self.db.execute("DELETE FROM versions WHERE id=?", (row["id"],))

    def get_file_versions(self, file_path=None, limit=200):
        if file_path:
            return self.db.query(
                "SELECT * FROM versions WHERE file_path=? ORDER BY created_at DESC",
                (os.path.abspath(file_path),),
            )
        return self.db.query(
            "SELECT * FROM versions ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )

    def restore_version(self, version_id, target_path=None):
        row = self.db.one("SELECT * FROM versions WHERE id=?", (version_id,))
        if not row or not os.path.isfile(row["version_path"]):
            return False
        target = target_path or row["file_path"]
        temporary = None
        try:
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            temporary = f"{target}.restore-{uuid.uuid4().hex[:10]}"
            # [FIX] ننسخ النسخة المطلوبة أولًا: create_version يستدعي التقليم الذي
            # قد يحذف أقدم نسخة، وهي بالضبط ما نريد استعادته عند بلوغ الحد.
            shutil.copy2(row["version_path"], temporary)
            if os.path.exists(target):
                self.create_version(target, "backup_before_restore")
            os.replace(temporary, target)
            temporary = None
            now_ns = time.time_ns()
            os.utime(target, ns=(now_ns, now_ns))
            return True
        except OSError as exc:
            if temporary:
                with contextlib.suppress(OSError):
                    os.remove(temporary)
            log.error("فشل استعادة الإصدار: %s", exc)
            return False

    def move_to_trash(self, file_path, reason="deleted"):
        try:
            if not os.path.exists(file_path):
                return False
            name = (
                f"{datetime.datetime.now():%Y%m%d_%H%M%S}_"
                f"{uuid.uuid4().hex[:6]}_{os.path.basename(file_path)}"
            )
            trash_path = self.trash_dir / name
            shutil.move(file_path, trash_path)
            size = os.path.getsize(trash_path) if os.path.isfile(trash_path) else 0
            self.db.execute(
                "INSERT INTO trash(original_path,trash_path,deleted_at,reason,size) VALUES(?,?,?,?,?)",
                (os.path.abspath(file_path), str(trash_path), time.time(), reason, size),
            )
            return True
        except OSError as exc:
            log.error("فشل نقل الملف إلى السلة: %s", exc)
            return False

    def list_trash(self):
        return self.db.query("SELECT * FROM trash ORDER BY deleted_at DESC LIMIT 500")

    def restore_from_trash(self, trash_id):
        row = self.db.one("SELECT * FROM trash WHERE id=?", (trash_id,))
        if not row or not os.path.exists(row["trash_path"]):
            return False
        try:
            destination = row["original_path"]
            parent = os.path.dirname(destination)
            if parent:
                os.makedirs(parent, exist_ok=True)
            if os.path.exists(destination):
                destination = unique_path(destination)
            os.replace(row["trash_path"], destination)
            self.db.execute("DELETE FROM trash WHERE id=?", (trash_id,))
            return True
        except OSError as exc:
            log.error("فشل الاستعادة من السلة: %s", exc)
            return False

    def empty_trash(self, older_than_days=None):
        cutoff = time.time() - older_than_days * 86400 if older_than_days else None
        removed = 0
        for row in self.db.query("SELECT * FROM trash"):
            if cutoff is not None and row["deleted_at"] >= cutoff:
                continue
            with contextlib.suppress(OSError):
                if os.path.isdir(row["trash_path"]):
                    shutil.rmtree(row["trash_path"])
                elif os.path.exists(row["trash_path"]):
                    os.remove(row["trash_path"])
            self.db.execute("DELETE FROM trash WHERE id=?", (row["id"],))
            removed += 1
        return removed

    def cleanup(self):
        cutoff = time.time() - self.config.version_retention_days * 86400
        rows = self.db.query(
            "SELECT id,version_path FROM versions WHERE created_at<?",
            (cutoff,),
        )
        for row in rows:
            with contextlib.suppress(OSError):
                os.remove(row["version_path"])
            self.db.execute("DELETE FROM versions WHERE id=?", (row["id"],))
        self.empty_trash(self.config.trash_retention_days)

    def get_stats(self):
        trash = self.db.one("SELECT COUNT(*) n, COALESCE(SUM(size),0) s FROM trash")
        return {
            "conflicts_count": self.db.one("SELECT COUNT(*) n FROM conflicts")["n"],
            "resolved_conflicts": self.db.one("SELECT COUNT(*) n FROM conflicts WHERE resolved=1")["n"],
            "open_conflicts": self.db.one("SELECT COUNT(*) n FROM conflicts WHERE resolved=0")["n"],
            "trash_size": trash["s"],
            "trash_items": trash["n"],
            "versions_count": self.db.one("SELECT COUNT(*) n FROM versions")["n"],
        }


class SyncEngine:
    def __init__(self, config):
        self.config = config
        self.db = Database(config.data_dir / "state.db")
        self.delta = DeltaSync()
        self.codec = FrameCodec(config)
        self.p2p_protocol = P2PProtocol(config)
        self.client = PeerClient(config, self.codec, self.p2p_protocol)
        self.file_watcher = FileWatcher(config, ignore_fn=self._watch_ignore)
        self.task_queue = TaskQueue(config.max_workers)
        self.conflict_resolver = ConflictResolver(self.db, config.data_dir, config)
        self.notifier = None
        self._fire_webhook = None
        self.running = False
        # Guards against calling ``close()`` twice (which would re-shutdown
        # the hash pool and re-close the SQLite connection).
        self._closed = False
        self.sync_state = {
            "active": False,
            "last_sync": None,
            "sync_count": 0,
            "errors": [],
            "started_at": None,
        }
        self.counters = {
            "bytes_sent": 0,
            "bytes_received": 0,
            "files_pulled": 0,
            "files_deleted": 0,
            "conflicts": 0,
        }
        self._share_locks = {}
        self._peer_locks = {}
        self._locks_guard = threading.Lock()
        self._dirty = collections.defaultdict(set)
        self._dirty_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._stop = threading.Event()
        self._threads = []
        self._retry_timers = set()
        self._last_cycle = 0.0
        self._last_cleanup = 0.0
        self._path_index = ()
        self._path_index_lock = threading.RLock()
        self._hash_workers = max(1, min(4, int(config.max_workers)))
        self._hash_pool = ThreadPoolExecutor(
            max_workers=self._hash_workers,
            thread_name_prefix="file-hash",
        )
        self.file_watcher.register_callback(self._on_file_changed)
        self._rebuild_path_index()

    def _share_lock(self, share):
        with self._locks_guard:
            return self._share_locks.setdefault(share, threading.RLock())

    def notify(self, title, message, kind="info"):
        notifier = self.notifier
        if notifier:
            with contextlib.suppress(Exception):
                notifier.show_notification(title, message, kind)

    def _log_activity(self, share, path, peer, action, size=0, ok=True, detail=""):
        self.db.execute(
            "INSERT INTO sync_log(ts,share,path,peer,action,size,ok,detail) VALUES(?,?,?,?,?,?,?,?)",
            (time.time(), share, path, peer, action, size, 1 if ok else 0, detail),
        )

    def recent_activity(self, limit=50):
        limit = max(1, min(1000, int(limit)))
        return self.db.query("SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,))

    def _rebuild_path_index(self):
        entries = []
        for share, root in self.config.shares().items():
            absolute = os.path.normcase(os.path.abspath(root))
            entries.append((absolute, share, os.path.abspath(root)))
        entries.sort(key=lambda item: len(item[0]), reverse=True)
        with self._path_index_lock:
            self._path_index = tuple(entries)

    def locate(self, abs_path):
        original = os.path.abspath(abs_path)
        normalized = os.path.normcase(original)
        with self._path_index_lock:
            entries = self._path_index
        for root_norm, share, root in entries:
            if normalized == root_norm or normalized.startswith(root_norm + os.sep):
                relative = os.path.relpath(original, root).replace(os.sep, "/")
                return None if relative == "." else (share, relative)
        return None

    def _watch_ignore(self, abs_path):
        location = self.locate(abs_path)
        return location is None or is_ignored(location[1], self.config.ignore_patterns)

    @staticmethod
    def _prefix_range(prefix):
        """حدّا نطاق لكل المسارات التي تبدأ بـ ``prefix`` (ينتهي بـ "/").

        [FIX] بديل دقيق وحساس لحالة الأحرف عن ``LIKE`` (الذي يعامل ``_`` و ``%``
        كأحرف بدل ويتجاهل حالة الأحرف في SQLite): ``a/`` → ``[a/, a0)``.
        """
        return prefix, prefix[:-1] + chr(ord("/") + 1)

    def _walk(self, root, sub=None, errors=None):
        start = os.path.join(root, *sub.split("/")) if sub else root
        stack = [(start, 0)]
        recursive = bool(self.config.watch_subdirectories)
        patterns = self.config.ignore_patterns
        while stack:
            directory, depth = stack.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        try:
                            if is_ignored(entry.name, patterns):
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                if recursive or depth == 0:
                                    stack.append((entry.path, depth + 1))
                            elif entry.is_file(follow_symlinks=False):
                                yield entry.path, entry.stat(follow_symlinks=False)
                        except OSError:
                            if errors is not None:
                                errors.append(entry.path)
                            continue
            except OSError:
                if errors is not None:
                    errors.append(directory)
                continue

    @staticmethod
    def _hash_candidate(candidate):
        full, size, mtime_ns = candidate
        try:
            digest = file_hash(full, max_size=MAX_HASH_SIZE_BYTES)
            st = os.stat(full)
        except ValueError:
            return (full, None, "oversized")
        except OSError:
            return None
        if st.st_size > MAX_HASH_SIZE_BYTES:
            return (full, None, "oversized")
        if st.st_size != size or st.st_mtime_ns != mtime_ns:
            return (full, None, True)
        return (full, digest, False)

    def scan_share(self, share, sub=None):
        root = self.config.shares().get(share)
        if not root or not os.path.isdir(root):
            return False
        prefix = (sub + "/") if sub else ""
        with self._share_lock(share):
            with self.db.lock:
                if prefix:
                    lo, hi = self._prefix_range(prefix)
                    cursor = self.db.conn.execute(
                        "SELECT path,size,mtime_ns,hash,deleted,oversized FROM files "
                        "WHERE share=? AND path>=? AND path<?", (share, lo, hi))
                else:
                    cursor = self.db.conn.execute(
                        "SELECT path,size,mtime_ns,hash,deleted,oversized FROM files WHERE share=?",
                        (share,))
                rows = {}
                while True:
                    batch = cursor.fetchmany(2000)
                    if not batch:
                        break
                    for row in batch:
                        rows[row["path"]] = dict(row)

        seen = set()
        candidates = []
        oversized_upserts = []
        unstable = False
        now_ns = time.time_ns()
        walk_errors: list = []
        for full, stat in self._walk(root, sub, walk_errors):
            relative = os.path.relpath(full, root).replace(os.sep, "/")
            seen.add(relative)
            row = rows.get(relative)
            if stat.st_size > MAX_HASH_SIZE_BYTES:
                if (row and row.get("oversized")
                        and row["size"] == stat.st_size
                        and row["mtime_ns"] == stat.st_mtime_ns):
                    continue
                old_hash = row["hash"] if row and not row["deleted"] else None
                oversized_upserts.append(
                    (share, relative, stat.st_size, stat.st_mtime_ns,
                     old_hash, 0, time.time(), 1)
                )
                log.warning(
                    "Skipping oversized sync file (>2GB): %s", full
                )
                continue
            if (row and not row["deleted"] and not row.get("oversized")
                    and row["size"] == stat.st_size
                    and row["mtime_ns"] == stat.st_mtime_ns):
                continue
            if now_ns - stat.st_mtime_ns < 1_500_000_000:
                unstable = True
                continue
            candidates.append((full, stat.st_size, stat.st_mtime_ns, relative))

        upserts = []
        if candidates:
            futures = [self._hash_pool.submit(self._hash_candidate, item[:3]) for item in candidates]
            for item, future in zip(candidates, futures):
                result = future.result()
                if result is None:
                    continue
                full, digest, changed = result
                if changed == "oversized":
                    try:
                        stat = os.stat(full)
                    except OSError:
                        continue
                    relative = item[3]
                    row = rows.get(relative)
                    old_hash = row["hash"] if row and not row["deleted"] else None
                    oversized_upserts.append(
                        (share, relative, stat.st_size, stat.st_mtime_ns,
                         old_hash, 0, time.time(), 1)
                    )
                    log.warning(
                        "Skipping sync file that grew beyond 2GB while hashing: %s",
                        full,
                    )
                    continue
                if changed:
                    unstable = True
                    continue
                _, size, mtime_ns, relative = item
                if digest is None:
                    unstable = True
                    continue
                upserts.append(
                    (share, relative, size, mtime_ns, digest, 0, time.time(), 0)
                )

        # [FIX] أي مجلد/ملف تعذّرت قراءته (انقطاع شبكة، صلاحيات، قرص غير مركّب)
        # لا يعني أن محتواه حُذف. كنا نعلّم كل ما تحته «محذوفًا» فيصل الحذف الجماعي
        # إلى النظراء. نستثني هذه المسارات من اكتشاف الحذف في هذه الدورة.
        blocked = []
        for err_path in walk_errors:
            rel_err = os.path.relpath(err_path, root).replace(os.sep, "/")
            blocked.append("" if rel_err == "." else rel_err)

        def _is_blocked(path):
            return any(b == "" or path == b or path.startswith(b + "/") for b in blocked)

        removed = []
        for relative, row in rows.items():
            if not row["deleted"] and relative not in seen and not _is_blocked(relative):
                removed.append((time.time(), share, relative))

        changed = bool(upserts or oversized_upserts or removed)
        if changed:
            with self._share_lock(share):
                if upserts or oversized_upserts:
                    self.db.many(
                        "INSERT OR REPLACE INTO files(share,path,size,mtime_ns,hash,deleted,mod_time,oversized) VALUES(?,?,?,?,?,?,?,?)",
                        upserts + oversized_upserts,
                    )
                if removed:
                    self.db.many(
                        "UPDATE files SET deleted=1, mod_time=? WHERE share=? AND path=?",
                        removed,
                    )
        if unstable:
            self._retry_later(share)
        return changed

    def _retry_later(self, share):
        with self._state_lock:
            if not self.running:
                return
            timer = threading.Timer(1.8, self._enqueue_scan, args=(share,))
            timer.daemon = True
            self._retry_timers.add(timer)
        timer.start()

    def _enqueue_scan(self, share):
        with self._state_lock:
            self._retry_timers = {timer for timer in self._retry_timers if timer.is_alive()}
            running = self.running
        if running:
            self.task_queue.add_task(
                {
                    "function": self._scan_and_notify,
                    "args": (share,),
                    "key": f"scan:{share}",
                    "type": "scan",
                },
                "high",
            )

    def _scan_and_notify(self, share):
        if self.scan_share(share):
            self._schedule_notify(share)

    def index_path(self, share, rel):
        root = self.config.shares().get(share)
        if not root:
            return "same"
        try:
            full = safe_join(root, rel)
        except PathError:
            return "same"
        if os.path.isdir(full):
            return "changed" if self.scan_share(share, rel) else "same"
        if not os.path.exists(full):
            with self._share_lock(share):
                row = self.db.one(
                    "SELECT 1 x FROM files WHERE share=? AND path=? AND deleted=0",
                    (share, rel),
                )
                lo, hi = self._prefix_range(rel + "/")
                child = self.db.one(
                    "SELECT 1 x FROM files WHERE share=? AND path>=? AND path<? AND deleted=0 LIMIT 1",
                    (share, lo, hi),
                )
                if not (row or child):
                    return "same"
                self.db.execute(
                    "UPDATE files SET deleted=1, mod_time=? WHERE share=? AND deleted=0 "
                    "AND (path=? OR (path>=? AND path<?))",
                    (time.time(), share, rel, lo, hi),
                )
            return "changed"
        return self._index_file(share, root, rel, full)

    def _index_file(self, share, root, rel, full):
        try:
            stat = os.stat(full)
        except OSError:
            return "same"
        with self._share_lock(share):
            row = self.db.one(
                "SELECT size,mtime_ns,hash,deleted,oversized FROM files WHERE share=? AND path=?",
                (share, rel),
            )
            if stat.st_size > MAX_HASH_SIZE_BYTES:
                if (row and row.get("oversized")
                        and row["size"] == stat.st_size
                        and row["mtime_ns"] == stat.st_mtime_ns):
                    return "same"
                old_hash = row["hash"] if row and not row["deleted"] else None
                self.db.execute(
                    "INSERT OR REPLACE INTO files"
                    "(share,path,size,mtime_ns,hash,deleted,mod_time,oversized) "
                    "VALUES(?,?,?,?,?,0,?,1)",
                    (share, rel, stat.st_size, stat.st_mtime_ns,
                     old_hash, time.time()),
                )
                log.warning("Skipping oversized sync file (>2GB): %s", full)
                return "oversized"
            if (row and not row["deleted"] and not row.get("oversized")
                    and row["size"] == stat.st_size
                    and row["mtime_ns"] == stat.st_mtime_ns):
                return "same"
        if time.time_ns() - stat.st_mtime_ns < 1_500_000_000:
            return "unstable"
        try:
            digest = file_hash(full)
            stat2 = os.stat(full)
        except OSError:
            return "same"
        if (stat2.st_size, stat2.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
            return "unstable"
        with self._share_lock(share):
            self.db.execute(
                "INSERT OR REPLACE INTO files(share,path,size,mtime_ns,hash,deleted,mod_time) VALUES(?,?,?,?,?,0,?)",
                (share, rel, stat2.st_size, stat2.st_mtime_ns, digest, time.time()),
            )
        return "changed"

    def manifest(self, share):
        self.scan_share(share)
        rows = self.db.query(
            "SELECT path,size,mtime_ns,hash,deleted,mod_time,oversized FROM files WHERE share=?",
            (share,),
        )
        return {
            row["path"]: {
                "size": row["size"],
                "mtime_ns": row["mtime_ns"],
                "hash": row["hash"],
                "deleted": row["deleted"],
                "oversized": bool(row.get("oversized")),
                "mod_time": row["mod_time"],
            }
            for row in rows
        }

    def _sanitize_remote_mtime_ns(self, value):
        now_ns = time.time_ns()
        try:
            mtime_ns = int(value or 0)
        except (TypeError, ValueError):
            mtime_ns = 0
        try:
            skew_s = int(getattr(self.config, "peer_mtime_skew_seconds", 300))
        except (TypeError, ValueError):
            skew_s = 300
        max_future_ns = now_ns + max(0, skew_s) * 1_000_000_000
        max_past_ns = now_ns - 365 * 24 * 3600 * 1_000_000_000
        if mtime_ns > max_future_ns or (
            mtime_ns and mtime_ns < max_past_ns
        ):
            return now_ns, True
        return mtime_ns, False

    def _sanitize_remote_manifest(self, files):
        if not isinstance(files, dict):
            return {}
        sanitized = {}
        for rel, original in files.items():
            if not isinstance(rel, str) or not isinstance(original, dict):
                continue
            try:
                clean = sanitize_relpath(rel)
            except PathError:
                continue
            meta = dict(original)
            try:
                size = int(meta.get("size") or 0)
            except (TypeError, ValueError):
                continue
            meta["oversized"] = size > MAX_HASH_SIZE_BYTES
            meta["mtime_ns"], clamped = self._sanitize_remote_mtime_ns(
                meta.get("mtime_ns")
            )
            if clamped:
                meta["_clamped"] = True
            sanitized[clean] = meta
        return sanitized

    def _on_file_changed(self, event):
        paths = [event["path"]]
        if event.get("src"):
            paths.append(event["src"])
        shares = set()
        with self._dirty_lock:
            for path in paths:
                location = self.locate(path)
                if location:
                    shares.add(location[0])
                    self._dirty[location[0]].add(location[1])
        for share in shares:
            self.task_queue.add_task(
                {
                    "function": self._process_dirty,
                    "args": (share,),
                    "key": f"dirty:{share}",
                    "type": "index",
                },
                "high",
            )

    def _process_dirty(self, share):
        with self._dirty_lock:
            rels = self._dirty.pop(share, set())
        changed = False
        retry = set()
        for relative in rels:
            result = self.index_path(share, relative)
            if result == "changed":
                changed = True
            elif result == "unstable":
                retry.add(relative)
        if retry:
            with self._dirty_lock:
                self._dirty[share].update(retry)
            self._retry_later(share)
        if changed:
            self._schedule_notify(share)

    def _schedule_notify(self, share):
        self.task_queue.add_task(
            {
                "function": self._notify_peers,
                "args": (share,),
                "key": f"notify:{share}",
                "type": "notify",
            },
            "high",
        )

    def _notify_peers(self, share):
        for peer in self.p2p_protocol.online_peers():
            try:
                self.client.call_json(peer, "POST", "/p2p/notify", {"share": share}, timeout=4)
            except (PeerError, OSError, ValueError, http.client.HTTPException):
                continue

    def request_sync(self, share, peer_id):
        return self.task_queue.add_task(
            {
                "function": self.sync_share_with_peer,
                "args": (share, peer_id),
                "key": f"sync:{share}:{peer_id}",
                "type": "sync",
            },
            "high",
        )

    def _set_base(self, peer_id, share, rel, digest):
        self.db.execute(
            "INSERT OR REPLACE INTO peer_base(peer,share,path,hash) VALUES(?,?,?,?)",
            (peer_id, share, rel, digest or ""),
        )

    def _record_error(self, message):
        with self._state_lock:
            errors = list(self.sync_state["errors"])
            errors.append({"time": time.time(), "error": message})
            self.sync_state["errors"] = errors[-20:]

    def sync_share_with_peer(self, share, peer_id):
        peer = self.p2p_protocol.get_peer(peer_id)
        if not peer:
            return {"success": False, "reason": "peer_unknown"}
        with self._locks_guard:
            lock = self._peer_locks.setdefault((peer_id, share), threading.Lock())
        if not lock.acquire(blocking=False):
            return {"success": False, "reason": "busy"}
        try:
            try:
                remote_data = self.client.call_json(
                    peer,
                    "GET",
                    "/p2p/manifest?share=" + urllib.parse.quote(share),
                    timeout=30,
                )
            except PeerError as exc:
                if exc.status == 404:
                    return {"success": True, "skipped": "share_not_on_peer"}
                if exc.status == 401:
                    return {"success": False, "reason": "auth_failed"}
                raise
            except (OSError, http.client.HTTPException):
                return {"success": False, "reason": "unreachable"}

            remote = self._sanitize_remote_manifest(remote_data.get("files", {}))
            remote_node = remote_data.get("node", peer_id)
            self.scan_share(share)
            local = {row["path"]: row for row in self.db.query("SELECT * FROM files WHERE share=?", (share,))}
            base = {
                row["path"]: row["hash"]
                for row in self.db.query(
                    "SELECT path,hash FROM peer_base WHERE peer=? AND share=?",
                    (peer_id, share),
                )
            }

            pulls = []
            deletes = []
            local_ahead = False
            paths = set(local)
            paths.update(remote)
            for relative in paths:
                if is_ignored(relative, self.config.ignore_patterns):
                    continue
                try:
                    sanitize_relpath(relative)
                except PathError:
                    continue
                local_row = local.get(relative)
                remote_row = remote.get(relative)
                if ((local_row and local_row.get("oversized"))
                        or (remote_row and remote_row.get("oversized"))):
                    continue
                local_hash = local_row["hash"] if local_row and not local_row["deleted"] else None
                remote_hash = remote_row.get("hash") if remote_row and not remote_row.get("deleted") else None
                base_hash = base.get(relative) or None

                if local_hash == remote_hash:
                    if local_hash is not None and base_hash != local_hash:
                        self._set_base(peer_id, share, relative, local_hash)
                    elif local_hash is None and base_hash:
                        self._set_base(peer_id, share, relative, "")
                    continue

                local_changed = local_hash != base_hash
                remote_changed = remote_hash != base_hash
                if remote_changed and not local_changed:
                    if remote_hash is None:
                        deletes.append(relative)
                    else:
                        pulls.append((relative, remote_row, local_row, None))
                elif local_changed and not remote_changed:
                    local_ahead = True
                else:
                    if local_hash is None:
                        pulls.append((relative, remote_row, local_row, None))
                    elif remote_hash is None:
                        local_ahead = True
                    else:
                        winner = self.conflict_resolver.decide(
                            self.config.conflict_resolution,
                            dict(local_row),
                            dict(remote_row),
                            self.config.node_id,
                            remote_node,
                        )
                        if winner == "remote":
                            pulls.append((relative, remote_row, local_row, "conflict"))
                        else:
                            self.conflict_resolver.record_conflict(
                                share,
                                relative,
                                peer_id,
                                self.config.conflict_resolution,
                                "local",
                                local_hash,
                                remote_hash,
                                False,
                            )
                            local_ahead = True

            pulls.sort(key=lambda item: int(item[1].get("size") or 0))
            done = failed = 0
            for relative, remote_row, local_row, reason in pulls:
                try:
                    if reason == "conflict":
                        self._handle_conflict_loss(share, relative, peer_id, local_row, remote_row)
                    self._pull_file(peer, share, relative, remote_row, local_row)
                    done += 1
                except Exception as exc:
                    failed += 1
                    self._record_error(f"{relative}: {exc}")
                    self._log_activity(share, relative, peer_id, "pull", ok=False, detail=str(exc))

            for relative in deletes:
                try:
                    self._apply_remote_delete(share, relative, peer_id, local.get(relative))
                    done += 1
                except Exception as exc:
                    failed += 1
                    self._record_error(f"{relative}: {exc}")

            if done:
                self.notify(
                    "اكتملت المزامنة",
                    f"{done} عنصر من {peer.get('name', peer_id)} ({share})",
                    "success",
                )
                self._schedule_notify(share)
                callback = self._fire_webhook
                if callable(callback):
                    with contextlib.suppress(Exception):
                        callback(
                            "sync_complete",
                            {"share": share, "peer": peer_id, "pulled": done, "failed": failed},
                        )
            elif local_ahead:
                with contextlib.suppress(Exception):
                    self.client.call_json(peer, "POST", "/p2p/notify", {"share": share}, timeout=4)

            return {"success": failed == 0, "pulled": done, "failed": failed}
        finally:
            lock.release()

    def _handle_conflict_loss(self, share, rel, peer_id, local_row, remote_row):
        strategy = self.config.conflict_resolution
        root = self.config.shares()[share]
        copy_rel = None
        if strategy == "ask":
            stem, ext = os.path.splitext(rel)
            copy_rel = (
                f".conflicts/{stem} (conflict {self.config.node_id[:6]} "
                f"{(local_row.get('hash') or 'unknown')[:6]}){ext}"
            )
            source = safe_join(root, rel)
            target = safe_join(root, copy_rel)
            if os.path.isfile(source) and not os.path.exists(target):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(source, target)
                self.index_path(share, copy_rel)
        conflict_id = self.conflict_resolver.record_conflict(
            share,
            rel,
            peer_id,
            strategy,
            "remote",
            local_row["hash"],
            remote_row["hash"],
            strategy == "ask",
            copy_rel,
            {
                "remote_mtime_ns": remote_row.get("mtime_ns"),
                "local_mtime_ns": local_row.get("mtime_ns"),
            },
        )
        self.counters["conflicts"] += 1
        self.notify("تعارض في الملفات", rel, "warning")
        callback = self._fire_webhook
        if callable(callback):
            with contextlib.suppress(Exception):
                callback(
                    "conflict_detected",
                    {"share": share, "path": rel, "peer": peer_id, "conflict_id": conflict_id},
                )

    def _apply_remote_delete(self, share, rel, peer_id, local_row):
        root = self.config.shares()[share]
        full = safe_join(root, rel)
        deleted = False
        with self._share_lock(share):
            if os.path.isfile(full) and local_row and not local_row["deleted"]:
                stat = os.stat(full)
                if (stat.st_size, stat.st_mtime_ns) != (local_row["size"], local_row["mtime_ns"]):
                    raise RuntimeError("الملف تغيّر محلياً — أُلغي الحذف")
                self.conflict_resolver.move_to_trash(full, "remote_delete")
                deleted = True
            self.db.execute(
                "UPDATE files SET deleted=1, mod_time=? WHERE share=? AND path=?",
                (time.time(), share, rel),
            )
            self._set_base(peer_id, share, rel, "")
        if deleted:
            self.counters["files_deleted"] += 1
        self._log_activity(share, rel, peer_id, "delete")
        # Notify other peers that this file is now gone on our side, so they
        # can propagate the deletion (or request a fresh manifest) instead of
        # waiting for the next scheduled cycle.
        self._schedule_notify(share)

    def _find_local_by_hash(self, share, digest, exclude):
        root = self.config.shares()[share]
        rows = self.db.query(
            "SELECT path FROM files WHERE share=? AND hash=? AND deleted=0 AND path<>? LIMIT 8",
            (share, digest, exclude),
        )
        for row in rows:
            with contextlib.suppress(PathError):
                candidate = safe_join(root, row["path"])
                if os.path.isfile(candidate):
                    return candidate
        return None

    def _pull_file(self, peer, share, rel, remote, local_row):
        root = self.config.shares()[share]
        destination = safe_join(root, rel)
        remote_size = int(remote.get("size") or 0)
        if remote_size < 0 or remote_size > self.config.max_file_size:
            raise RuntimeError("الملف أكبر من الحد المسموح")
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        # The temporary file MUST live in the destination's directory, not
        # in the share root: os.replace() below is only guaranteed to be
        # atomic within a single filesystem, and a share can contain
        # multiple mount points (e.g. a subdirectory that is itself a bind
        # mount or a symlink to another volume).  Using ``root`` here would
        # make ``os.replace`` fail with EXDEV on such layouts.
        temporary = destination + f".sync-tmp-{uuid.uuid4().hex}"
        try:
            done_hash = None
            remote_mtime_ns = int(remote.get("mtime_ns") or time.time_ns())
            sent = 0
            source = None
            if self.config.detect_moves and remote.get("hash"):
                source = self._find_local_by_hash(share, remote["hash"], rel)
            if source:
                shutil.copyfile(source, temporary)
                if file_hash(temporary) == remote["hash"]:
                    done_hash = remote["hash"]
                    self.delta._bump(bytes_saved=remote_size)

            if done_hash is None:
                basis = (
                    destination
                    if local_row and not local_row["deleted"] and os.path.isfile(destination)
                    else None
                )
                signature = self.delta.signature(basis) if basis else None
                payload = json.dumps(
                    {"share": share, "path": rel, "signature": signature},
                    separators=(",", ":"),
                ).encode("utf-8")
                response, connection = self.client.request(
                    peer,
                    "POST",
                    "/p2p/delta",
                    payload,
                    timeout=60,
                    extra_headers={"Content-Type": "application/json"},
                )
                try:
                    if response.status != 200:
                        raise PeerError(
                            response.status,
                            response.read(200).decode("utf-8", "replace"),
                        )
                    operations = self._response_ops(response)
                    first = next(operations, None)
                    if first is None:
                        raise IOError("رد فارغ من النظير")
                    if first[0] == "meta":
                        remote_mtime_ns = int(first[1].get("mtime_ns") or remote_mtime_ns)
                        operations = itertools.chain((first,), operations)
                    done_hash, _, sent = DeltaSync.apply(
                        operations,
                        temporary,
                        basis,
                        signature,
                    )
                    self.delta._bump(bytes_saved=max(0, remote_size - sent))
                finally:
                    connection.close()

            remote_mtime_ns, _ = self._sanitize_remote_mtime_ns(remote_mtime_ns)
            now_ns = max(1, remote_mtime_ns)
            os.utime(temporary, ns=(now_ns, now_ns))
            with self._share_lock(share):
                if os.path.exists(destination):
                    stat = os.stat(destination)
                    if local_row is None:
                        # Only snapshot the pre-existing file when it is a
                        # file we would actually track.  Ignored paths
                        # (``.sync-tmp-*``, ``node_modules``, …) can churn
                        # endlessly and would otherwise fill the versions
                        # directory with garbage.
                        if not is_ignored(rel, self.config.ignore_patterns):
                            self.conflict_resolver.create_version(
                                destination, "before_sync_unindexed")
                    elif local_row.get("deleted"):
                        self.conflict_resolver.create_version(destination, "before_sync_deleted")
                    elif (
                        local_row.get("hash") is not None
                        and file_hash(destination) != local_row.get("hash")
                    ) or (
                        local_row.get("hash") is None
                        and (stat.st_size, stat.st_mtime_ns)
                        != (local_row.get("size"), local_row.get("mtime_ns"))
                    ):
                        raise RuntimeError("الملف تغيّر محلياً أثناء النقل — سيُعاد التقييم")
                    else:
                        self.conflict_resolver.create_version(destination, "before_sync")
                os.replace(temporary, destination)
                stat = os.stat(destination)
                self.db.execute(
                    "INSERT OR REPLACE INTO files(share,path,size,mtime_ns,hash,deleted,mod_time) VALUES(?,?,?,?,?,0,?)",
                    (share, rel, stat.st_size, stat.st_mtime_ns, done_hash, time.time()),
                )
                self._set_base(peer["id"], share, rel, done_hash)
            self.counters["files_pulled"] += 1
            self._log_activity(
                share,
                rel,
                peer["id"],
                "pull",
                stat.st_size,
                True,
                f"نُقل {human_size(sent)}",
            )
        finally:
            self.delta.invalidate(destination)
            with contextlib.suppress(OSError):
                os.remove(temporary)

    def _response_ops(self, response):
        for payload, size in self.codec.read_frames(response):
            self.counters["bytes_received"] += size
            self.p2p_protocol._bump_stats(bytes_received=size)
            yield self.delta.decode_op(payload)

    def p2p_delta_stream(self, share, rel, sig):
        def frame(op):
            data = self.codec.encode(self.delta.encode_op(op))
            self.counters["bytes_sent"] += len(data)
            self.p2p_protocol._bump_stats(bytes_sent=len(data))
            return data
        try:
            root = self.config.shares().get(share)
            if not root:
                raise PathError("مشاركة غير معروفة")
            full = safe_join(root, rel)
            stat = os.stat(full)
            yield frame(("meta", {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}))
            for op in self.delta.iter_delta(full, sig):
                if op[0] == "end":
                    stat2 = os.stat(full)
                    if (stat2.st_size, stat2.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
                        yield frame(("error", "الملف تغيّر أثناء الإرسال"))
                        return
                yield frame(op)
        except (OSError, PathError, ValueError) as exc:
            yield frame(("error", str(exc)))

    def send_file_to_peer(self, peer_id, path):
        peer = self.p2p_protocol.get_peer(peer_id)
        if not peer:
            return False, i18n.t("sync.peer_unknown")
        full = None
        for _, root in self.config.shares().items():
            with contextlib.suppress(PathError):
                if os.path.isabs(path):
                    # [FIX] abspath لا يحلّ الروابط الرمزية: رابط داخل المشاركة يشير إلى
                    # خارجها كان يمرّ. نتحقق بـ realpath أنه ضمن جذر المشاركة فعليًا.
                    candidate = os.path.realpath(path)
                    real_root = os.path.realpath(root)
                    if not (candidate == real_root or candidate.startswith(real_root + os.sep)):
                        continue
                else:
                    candidate = safe_join(root, path)
                if os.path.isfile(candidate) and self.locate(candidate):
                    full = candidate
                    break
        if not full:
            return False, i18n.t("sync.file_not_in_shares")
        name = os.path.basename(full)
        response, connection = self.client.request(
            peer,
            "POST",
            "/p2p/inbox?name=" + urllib.parse.quote(name),
            timeout=600,
            file_path=full,
        )
        try:
            body = response.read()
        finally:
            connection.close()
        if response.status != 200:
            return False, i18n.t("sync.peer_rejected", status=response.status)
        self.counters["bytes_sent"] += os.path.getsize(full)
        return True, json.loads(body).get("name", name)

    def _sync_loop(self):
        while not self._stop.wait(1.0):
            if time.time() - self._last_cycle < max(1, self.config.sync_interval):
                continue
            self._last_cycle = time.time()
            try:
                self._perform_sync_cycle()
            except Exception as exc:
                log.error("خطأ في دورة المزامنة: %s", exc)
                self._record_error(str(exc))

    def _perform_sync_cycle(self):
        shares = tuple(self.config.shares())
        for share in shares:
            self.task_queue.add_task(
                {
                    "function": self._scan_and_notify,
                    "args": (share,),
                    "key": f"scan:{share}",
                    "type": "scan",
                },
                "low",
            )
        manual_peers = tuple(self.config.manual_peers)
        known_peers = self.p2p_protocol.all_peers()
        for address in manual_peers:
            host, _, port = address.rpartition(":")
            known = next(
                (
                    peer
                    for peer in known_peers
                    if peer["ip"] == host and str(peer["port"]) == port
                ),
                None,
            )
            if not known or not known.get("online") or time.time() - known.get("last_seen", 0) > 30:
                self.task_queue.add_task(
                    {
                        "function": self.p2p_protocol.add_manual_peer,
                        "args": (address,),
                        "kwargs": {"persist": False, "client": self.client},
                        "key": f"peer-refresh:{address}",
                        "type": "peer_refresh",
                    },
                    "low",
                )
        for peer in self.p2p_protocol.online_peers():
            for share in shares:
                self.request_sync(share, peer["id"])
        if time.time() - self._last_cleanup > 3600:
            self._last_cleanup = time.time()
            self.task_queue.add_task(
                {"function": self.conflict_resolver.cleanup, "type": "cleanup"},
                "low",
            )
        with self._state_lock:
            self.sync_state["last_sync"] = time.time()
            self.sync_state["sync_count"] += 1

    def sync_now(self):
        self._last_cycle = 0.0

    def start(self):
        with self._state_lock:
            if self.running:
                return
            if self._closed:
                raise RuntimeError(
                    "SyncEngine has been closed and cannot be restarted. "
                    "Create a new instance instead."
                )
            self.running = True
            self._stop.clear()
        self.task_queue.max_workers = max(2, int(self.config.max_workers))
        self.task_queue.allowed_workers = self.task_queue.max_workers
        self.task_queue.start()
        self.file_watcher.start()
        self.p2p_protocol.start()
        self._rebuild_path_index()
        for share, root in self.config.shares().items():
            self.file_watcher.add_watch_path(root, self.config.watch_subdirectories)
            self._enqueue_scan(share)
        thread = threading.Thread(target=self._sync_loop, daemon=True, name="sync-loop")
        thread.start()
        self._threads = [thread]
        with self._state_lock:
            self.sync_state.update(active=True, started_at=time.time())

    def stop(self):
        """Stop all background workers.

        The hash thread-pool is intentionally left alive so the engine can
        be restarted later via :meth:`start`.  For permanent teardown call
        :meth:`close`, which also releases the pool and the SQLite handle.
        """
        with self._state_lock:
            if not self.running:
                return
            self.running = False
            self._stop.set()
            timers = tuple(self._retry_timers)
            self._retry_timers.clear()
        for timer in timers:
            with contextlib.suppress(Exception):
                timer.cancel()
        failures = []
        for component in (self.file_watcher, self.p2p_protocol, self.task_queue):
            try:
                component.stop()
            except Exception as exc:
                failures.append(exc)
        for thread in self._threads:
            try:
                thread.join(timeout=3)
            except Exception as exc:
                failures.append(exc)
        self._threads = []
        with self._state_lock:
            self.sync_state["active"] = False
        if failures:
            for exc in failures:
                log.error(
                    "Background component failed to stop: %s",
                    exc,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
            raise failures[0]

    def close(self):
        """Permanent teardown: stop, release the hash pool, close the DB.

        Idempotent — safe to call multiple times (e.g. from both
        ``SuperiorSyncApp.shutdown`` and an ``atexit`` handler).

        [FIX-MIN-15] ترتيب الإغلاق: نضع ``_closed = True`` **بعد**
        نجاح كل خطوة.  سابقاً كان يُعيَّن قبل ``stop()``، فإذا رفع
        ``stop()`` استثناءً يبقى ``_closed=True`` رغم أن الموارد لم
        تُحرَّر — فلا يمكن إعادة المحاولة.  الآن أي فشل في ``stop()``
        أو ``db.close()`` يترك ``_closed=False`` ليتمكّن المتصل من
        إعادة المحاولة بأمان (كل الدوال الداخلية idempotent).
        """
        if self._closed:
            return
        # ``stop()`` idempotent ومحمي بـ ``if not self.running: return``،
        # لذا إعادة استدعائه بعد فشل جزئي آمنة.
        self.stop()
        with contextlib.suppress(Exception):
            self._hash_pool.shutdown(wait=True, cancel_futures=True)
        self.db.close()
        self._closed = True

    def add_sync_folder(self, folder_path):
        folder = os.path.abspath(os.path.expanduser(str(folder_path)))
        if not os.path.isdir(folder):
            return False, i18n.t("sync.folder_missing")
        # [FIX] لا تحقق سابقًا: كان يمكن إضافة /etc أو مجلد يحتوي data_dir نفسه
        # (فتُشارك قاعدة البيانات وملفات الإعداد مع كل النظراء).
        try:
            validate_sync_folder(folder, self.config.data_dir)
        except ValueError as exc:
            if "overlaps" in str(exc):
                return False, i18n.t("sync.folder_is_data_dir")
            return False, i18n.t("error.path_unsafe")
        for _, root in self.config.shares().items():
            normalized = os.path.abspath(root)
            if folder == normalized or folder.startswith(normalized + os.sep) or normalized.startswith(folder + os.sep):
                return False, i18n.t("sync.folder_overlap", path=normalized)
        with self.config.lock:
            if folder in self.config.sync_folders:
                return False, i18n.t("sync.folder_exists")
            self.config.sync_folders.append(folder)
        self.config.save()
        self.config.invalidate_shares()
        self._rebuild_path_index()
        if self.running:
            share_id = next(
                (share for share, path in self.config.shares().items()
                 if path == folder),
                None,
            )
            if share_id is None:
                raise RuntimeError(f"Added sync folder is missing from shares: {folder}")
            self.file_watcher.add_watch_path(folder, self.config.watch_subdirectories)
            self._enqueue_scan(share_id)
        return True, None

    def remove_sync_folder(self, folder_path):
        folder = os.path.abspath(os.path.expanduser(str(folder_path)))
        with self.config.lock:
            if folder not in self.config.sync_folders:
                return False
            share_ids = [share for share, path in self.config.shares().items() if path == folder]
            self.config.sync_folders.remove(folder)
        self.config.save()
        self.config.invalidate_shares()
        self._rebuild_path_index()
        self.file_watcher.remove_watch_path(folder)
        for share in share_ids:
            self.db.execute("DELETE FROM files WHERE share=?", (share,))
            self.db.execute("DELETE FROM peer_base WHERE share=?", (share,))
        return True

    def get_stats(self):
        delta_stats = self.delta.get_stats()
        records = self.db.one("SELECT COUNT(*) n FROM files WHERE deleted=0")["n"]
        with self._state_lock:
            state = dict(self.sync_state)
            state["errors"] = list(self.sync_state["errors"])
        return {
            "sync_state": state,
            "file_watcher": "active" if self.file_watcher.running else "inactive",
            "watcher_backend": self.file_watcher.backend_name(),
            "p2p_protocol": self.p2p_protocol.get_stats(),
            "delta_sync": delta_stats,
            "task_queue": self.task_queue.get_stats(),
            "conflict_resolver": self.conflict_resolver.get_stats(),
            "sync_records_count": records,
            "transfer": dict(self.counters),
            "node": {"id": self.config.node_id, "name": self.config.node_name},
        }