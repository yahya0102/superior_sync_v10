#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""بروتوكول النظراء (P2P) والتوقيع والتأطير."""
from __future__ import annotations

import base64
import collections
import contextlib
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import secrets
import socket
import struct
import threading
import time
import zlib

from . import i18n
# KDF parameters (salt + iteration count) live in config.py as the single
# source of truth.  Importing the derivation helpers directly means the
# P2P signing key and the frame-codec transport key can never drift from
# Config.hmac_key again (they used to disagree on both the salt version
# and the iteration count).
from .config import (
    SecurityError,
    derive_hmac_key as _derive_hmac_key,
    derive_transport_key as _derive_transport_key,
)
from .utils import HAS_CRYPTO, get_local_ips, log


class PeerError(Exception):
    def __init__(self, status, message=""):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


def sign_request(key, method, target, ts, body_sha, node, nonce=""):
    msg = f"{method}\n{target}\n{ts}\n{body_sha}\n{node}\n{nonce}".encode("utf-8")
    return hmac.new(_derive_hmac_key(key), msg,
                    hashlib.sha256).hexdigest()


def new_nonce() -> str:
    return secrets.token_urlsafe(16)


def read_exact(stream, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            if not buf:
                return b""
            raise IOError("انقطع الاتصال أثناء القراءة")
        buf.extend(chunk)
    return bytes(buf)


class FrameCodec:
    """تأطير البيانات مع ضغط zlib وتشفير Fernet."""

    MAX_FRAME = 64 * 1024 * 1024
    # سقف الحجم بعد فك الضغط (حماية من zip-bomb: إطار 300KB قد يتضخم إلى 300MB).
    MAX_DECODED = 128 * 1024 * 1024

    def __init__(self, config):
        self.config = config
        self._fkey = None
        self._f = None

    def invalidate_cache(self):
        self._fkey = None
        self._f = None

    def _fernet(self):
        if not HAS_CRYPTO:
            raise SecurityError("التشفير يتطلب: pip install cryptography")
        from cryptography.fernet import Fernet
        key = self.config.group_key
        if self._fkey != key:
            k = _derive_transport_key(key)
            self._f = Fernet(base64.urlsafe_b64encode(k))
            self._fkey = key
        return self._f

    def encode(self, payload):
        flags, data = 0, payload
        if self.config.enable_compression and len(data) > 128:
            c = zlib.compress(data, 1)
            if len(c) < len(data):
                data, flags = c, flags | 1
        if self.config.enable_encryption:
            if not HAS_CRYPTO:
                raise SecurityError(
                    "التشفير مُفعّل لكن cryptography غير مثبتة. "
                    "ثبّتها أو عطّل التشفير صراحةً من الإعدادات.")
            data, flags = self._fernet().encrypt(data), flags | 2
        return struct.pack(">BI", flags, len(data)) + data

    def decode(self, flags, data):
        if flags & 2:
            if not HAS_CRYPTO:
                raise SecurityError(
                    "استُقبل إطار مشفّر لكن cryptography غير مثبتة")
            from cryptography.fernet import InvalidToken
            try:
                data = self._fernet().decrypt(data)
            except InvalidToken as e:
                raise IOError(
                    "فشل فك تشفير الإطار (مفتاح مجموعة مختلف؟)") from e
        elif self.config.enable_encryption:
            # [FIX] كان بايت flags (يحدده المُرسل) يقرر هل يُفك التشفير، فيستطيع أي
            # وسيط حقن إطار غير مشفّر مقبول رغم تفعيل التشفير (downgrade).
            raise IOError("استُقبل إطار غير مشفّر بينما التشفير مُفعّل")
        if flags & 1:
            d = zlib.decompressobj()
            try:
                out = d.decompress(data, self.MAX_DECODED)
            except zlib.error as e:
                raise IOError("إطار مضغوط تالف") from e
            if d.unconsumed_tail or not d.eof:
                raise IOError("الإطار بعد فك الضغط أكبر من الحد المسموح")
            data = out
        return data

    def read_frames(self, stream):
        while True:
            hdr = read_exact(stream, 5)
            if not hdr:
                return
            flags, n = struct.unpack(">BI", hdr)
            if n > self.MAX_FRAME:
                raise IOError("إطار أكبر من الحد المسموح")
            yield self.decode(flags, read_exact(stream, n)), 5 + n


class P2PProtocol:
    """سجل النظراء + اكتشاف تلقائي."""

    MCAST_GROUP = "239.255.42.99"
    MCAST_PORT = 41900
    BCAST_PORT = 41901
    PEER_TTL = 60
    _SEEN_MAX = 5_000
    # يجب أن تتجاوز نافذة الطابع الزمني المقبولة (±120s = 240s) وإلا أمكن إعادة
    # تشغيل طلب بطابع مستقبلي بعد خروج الـ nonce من الذاكرة.
    _REPLAY_TTL = 300
    _REPLAY_MAX = 10_000

    def __init__(self, config):
        self.config = config
        self.peers = {}
        self.lock = threading.RLock()
        self.running = False
        self._threads = []
        self._stop = threading.Event()
        self.stats = {"peers_discovered": 0, "connections": 0,
                      "bytes_sent": 0, "bytes_received": 0,
                      "replay_dropped": 0}
        self._stats_lock = threading.Lock()
        self._seen_ever = collections.OrderedDict()
        self._replay = collections.OrderedDict()
        self._replay_lock = threading.Lock()

    def _bump_stats(self, **kw):
        with self._stats_lock:
            for k, v in kw.items():
                self.stats[k] = self.stats.get(k, 0) + v

    def remember_nonce(self, node: str, nonce: str) -> bool:
        if not nonce:
            return True
        key = f"{node}:{nonce}"
        now = time.time()
        with self._replay_lock:
            while self._replay:
                k, v = next(iter(self._replay.items()))
                if now - v > self._REPLAY_TTL:
                    self._replay.popitem(last=False)
                else:
                    break
            if key in self._replay:
                self._bump_stats(replay_dropped=1)
                return False
            self._replay[key] = now
            self._replay.move_to_end(key)
            while len(self._replay) > self._REPLAY_MAX:
                self._replay.popitem(last=False)
        return True

    @property
    def local_node_id(self):
        return self.config.node_id

    def start(self):
        if self.running:
            return
        self.running = True
        self._stop.clear()
        for target, name in ((self._listen_multicast, "mcast"),
                             (self._listen_broadcast, "bcast"),
                             (self._announce_loop, "announce")):
            t = threading.Thread(target=target, daemon=True,
                                 name=f"p2p-{name}")
            t.start()
            self._threads.append(t)
        for addr in list(self.config.manual_peers):
            ok, info = self.add_manual_peer(addr, persist=False)
            if not ok:
                hint = (" — تحقق من تطابق مفتاح المجموعة على الجهازين"
                        if "401" in str(info) else "")
                log.warning(
                    "⚠️ تعذّر الاتصال بالنظير %s: %s%s "
                    "(ستُعاد المحاولة تلقائياً)", addr, info, hint)
        log.info("🌐 بدء بروتوكول P2P — معرّف الجهاز: %s",
                 self.local_node_id)

    def stop(self):
        self.running = False
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)
        self._threads = []

    def touch(self, node_id, ip, port, name=None, shares=None,
              via="auto"):
        if not node_id or node_id == self.local_node_id:
            return None
        with self.lock:
            p = self.peers.get(node_id)
            new = p is None
            if new:
                p = {"id": node_id, "via": via,
                     "services": ["file_sync"],
                     "chunks_available": {}}
                self.peers[node_id] = p
            elif p.get("via") == "manual":
                via = "manual"
            update_data = {"ip": ip, "port": int(port),
                           "last_seen": time.time(), "online": True}
            if p.get("via") != "manual":
                update_data["via"] = via
            p.update(update_data)
            if name:
                p["name"] = name
            if shares is not None:
                p["shares"] = shares
            if node_id not in self._seen_ever:
                self._seen_ever[node_id] = time.time()
                self._seen_ever.move_to_end(node_id)
                while len(self._seen_ever) > self._SEEN_MAX:
                    self._seen_ever.popitem(last=False)
                self._bump_stats(peers_discovered=1)
                log.info("🔍 نظير جديد: %s @ %s:%s",
                         name or node_id, ip, port)
            else:
                self._seen_ever.move_to_end(node_id)
        return p

    def mark_failed(self, node_id):
        with self.lock:
            if node_id in self.peers:
                self.peers[node_id]["online"] = False

    def remove_peer(self, node_id):
        with self.lock:
            p = self.peers.pop(node_id, None)
        if p and p.get("via") == "manual":
            addr = f"{p['ip']}:{p['port']}"
            if addr in self.config.manual_peers:
                self.config.manual_peers.remove(addr)
                self.config.save()
        return p is not None

    def expire(self):
        now = time.time()
        with self.lock:
            for p in self.peers.values():
                if (p.get("via") != "manual"
                        and now - p.get("last_seen", 0) > self.PEER_TTL):
                    p["online"] = False

    def online_peers(self):
        with self.lock:
            return [dict(p) for p in self.peers.values()
                    if p.get("online")]

    def all_peers(self):
        with self.lock:
            return [dict(p) for p in self.peers.values()]

    def get_peer(self, node_id):
        with self.lock:
            p = self.peers.get(node_id)
            return dict(p) if p else None

    def add_manual_peer(self, addr, persist=True, client=None):
        try:
            host, _, port = addr.strip().rpartition(":")
            port = int(port)
            if not host:
                raise ValueError
        except ValueError:
            return False, i18n.t("sync.format_hostport")
        if client is None:
            client = PeerClient(self.config, FrameCodec(self.config), self)
        try:
            info = client.call_json(None, "GET", "/p2p/hello", timeout=5)
        except (PeerError, OSError, ValueError) as e:
            return False, i18n.t("sync.peer_connect_failed", err=e)
        self.touch(info["id"], host, port, info.get("name"),
                   info.get("shares"), via="manual")
        if persist:
            a = f"{host}:{port}"
            if a not in self.config.manual_peers:
                self.config.manual_peers.append(a)
                self.config.save()
        return True, info["id"]

    def _pack(self, msg):
        body = json.dumps(msg, sort_keys=True, separators=(",", ":"))
        nonce = new_nonce()
        wrapper = {"m": body, "n": nonce, "ts": time.time()}
        env = json.dumps(wrapper, sort_keys=True, separators=(",", ":")).encode("utf-8")
        sig = hmac.new(_derive_hmac_key(self.config.group_key),
                       env, hashlib.sha256).hexdigest()
        return json.dumps({"env": env.decode("utf-8"), "s": sig}).encode("utf-8")

    def _unpack(self, data):
        try:
            outer = json.loads(data.decode("utf-8"))
            env = outer["env"].encode("utf-8")
            good = hmac.new(_derive_hmac_key(self.config.group_key),
                            env, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(good, outer["s"]):
                return None
            wrapper = json.loads(outer["env"])
            msg = json.loads(wrapper["m"])
            if abs(time.time() - wrapper.get("ts", 0)) > 120:
                return None
            if not self.remember_nonce(msg.get("id", ""), wrapper.get("n", "")):
                return None
            return msg
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            return None

    def _announcement(self):
        return {"t": "announce", "id": self.local_node_id,
                "name": self.config.node_name,
                "port": self.config.active_port
                        or self.config.server_port,
                "shares": list(self.config.shares()),
                "ts": time.time()}

    def announce_presence(self):
        data = self._pack(self._announcement())
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                              socket.IPPROTO_UDP)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            targets = [(self.MCAST_GROUP, self.MCAST_PORT),
                       ("255.255.255.255", self.BCAST_PORT)]
            for ip in get_local_ips():
                with contextlib.suppress(ValueError):
                    net = ipaddress.ip_network(f"{ip}/24", strict=False)
                    targets.append((str(net.broadcast_address),
                                    self.BCAST_PORT))
            for t in targets:
                with contextlib.suppress(OSError):
                    s.sendto(data, t)
            s.close()
        except OSError as e:
            log.debug("تعذّر الإعلان: %s", e)

    def _announce_loop(self):
        while not self._stop.is_set():
            self.announce_presence()
            self.expire()
            self._stop.wait(10)

    def _handle_datagram(self, data, addr):
        msg = self._unpack(data)
        if (not msg or msg.get("t") != "announce"
                or msg.get("id") == self.local_node_id):
            return
        known = (msg["id"] in self.peers
                 and self.peers[msg["id"]].get("online"))
        self.touch(msg["id"], addr[0], msg.get("port", 8080),
                   msg.get("name"), msg.get("shares"))
        if not known:
            with contextlib.suppress(OSError):
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.sendto(self._pack(self._announcement()),
                         (addr[0], self.BCAST_PORT))
                s.close()

    def _listen(self, port, multicast):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                 socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                with contextlib.suppress(OSError):
                    sock.setsockopt(socket.SOL_SOCKET,
                                    socket.SO_REUSEPORT, 1)
            sock.bind(("", port))
            if multicast:
                joined = False
                for ip in get_local_ips() + ["0.0.0.0"]:
                    try:
                        mreq = (socket.inet_aton(self.MCAST_GROUP)
                                + socket.inet_aton(ip))
                        sock.setsockopt(socket.IPPROTO_IP,
                                        socket.IP_ADD_MEMBERSHIP, mreq)
                        joined = True
                    except OSError:
                        continue
                if not joined:
                    log.debug("تعذّر الانضمام لمجموعة multicast")
            sock.settimeout(1)
        except OSError as e:
            log.warning("تعذّر فتح مستمع UDP (%s): %s", port, e)
            return
        try:
            while not self._stop.is_set():
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                self._handle_datagram(data, addr)
        finally:
            sock.close()

    def _listen_multicast(self):
        self._listen(self.MCAST_PORT, True)

    def _listen_broadcast(self):
        self._listen(self.BCAST_PORT, False)

    def get_stats(self):
        s = dict(self.stats)
        s["peers_online"] = len(self.online_peers())
        s["node_id"] = self.local_node_id
        return s


class PeerClient:
    """عميل HTTP موقَّع للتواصل مع نظير."""

    def __init__(self, config, codec, p2p):
        self.config, self.codec, self.p2p = config, codec, p2p

    def _headers(self, method, target, body_sha, nonce):
        ts = str(int(time.time()))
        node = self.config.node_id
        return {"X-SS-Node": node, "X-SS-Ts": ts,
                "X-SS-Body": body_sha,
                "X-SS-Nonce": nonce,
                "X-SS-Sig": sign_request(
                    self.config.group_key, method, target,
                    ts, body_sha, node, nonce)}

    def request(self, peer, method, target, body=None, timeout=20,
                file_path=None, extra_headers=None):
        conn = http.client.HTTPConnection(
            peer["ip"], int(peer["port"]), timeout=timeout)
        fh = None
        try:
            if file_path:
                h = hashlib.sha256()
                with open(file_path, "rb") as f:
                    for b in iter(lambda: f.read(1 << 20), b""):
                        h.update(b)
                sha, length = h.hexdigest(), os.path.getsize(file_path)
                fh = open(file_path, "rb")
                payload = fh
            else:
                payload = body or b""
                sha = hashlib.sha256(payload).hexdigest()
                length = len(payload)
            nonce = new_nonce()
            headers = self._headers(method, target, sha, nonce)
            headers["Content-Length"] = str(length)
            if extra_headers:
                headers.update(extra_headers)
            conn.request(method, target, body=payload, headers=headers)
            self.p2p._bump_stats(connections=1, bytes_sent=length)
            resp = conn.getresponse()
            if peer.get("id") not in (None, "?"):
                self.p2p.touch(peer["id"], peer["ip"], peer["port"])
            return resp, conn
        except (OSError, http.client.HTTPException):
            conn.close()
            if peer.get("id") not in (None, "?"):
                self.p2p.mark_failed(peer["id"])
            raise
        finally:
            if fh:
                fh.close()

    def call_json(self, peer, method, target, obj=None, timeout=20):
        body = json.dumps(obj).encode("utf-8") if obj is not None else None
        resp, conn = self.request(
            peer, method, target, body, timeout,
            extra_headers={"Content-Type": "application/json"})
        try:
            data = resp.read()
        finally:
            conn.close()
        if resp.status != 200:
            try:
                msg = json.loads(data).get("error", "")
            except ValueError:
                msg = data[:100].decode("utf-8", "replace")
            raise PeerError(resp.status, msg)
        return json.loads(data)