"""Peer discovery and manual peer management."""
from __future__ import annotations

import http.client

from fastapi import APIRouter, Depends, HTTPException, Request, status

from .. import i18n
from ..dependencies import Principal, require_permission
from ..network import PeerError
from ..schemas import AddPeerRequest, SendToPeerRequest

router = APIRouter(prefix="/api/peers", tags=["peers"])


def _app(request: Request):
    return request.app.state.superior


@router.get("")
async def list_peers(request: Request, principal: Principal = Depends(require_permission("read"))):
    peers = _app(request).engine.p2p_protocol.all_peers()
    return {"peers": [{
        "id": p["id"],
        "name": p.get("name", p["id"][:8]),
        "ip": p["ip"],
        "port": p["port"],
        "services": p.get("services", []),
        "last_seen": p.get("last_seen", 0),
        "status": "online" if p.get("online") else "offline",
        "via": p.get("via"),
        "shares": p.get("shares", []),
    } for p in peers]}


@router.post("/discover")
async def discover(request: Request, principal: Principal = Depends(require_permission("write"))):
    _app(request).engine.p2p_protocol.announce_presence()
    return {"success": True}


@router.post("")
async def add_peer(payload: AddPeerRequest, request: Request,
                   principal: Principal = Depends(require_permission("configure"))):
    ok, info = _app(request).engine.p2p_protocol.add_manual_peer(payload.address)
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=info)
    return {"success": True, "peer_id": info}


@router.delete("/{peer_id}")
async def remove_peer(peer_id: str, request: Request,
                      principal: Principal = Depends(require_permission("configure"))):
    if not _app(request).engine.p2p_protocol.remove_peer(peer_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=i18n.t("error.not_found"))
    return {"success": True}


@router.post("/{peer_id}/send")
async def send_to_peer(peer_id: str, payload: SendToPeerRequest, request: Request,
                       principal: Principal = Depends(require_permission("share"))):
    app = _app(request)
    try:
        ok, msg = app.engine.send_file_to_peer(peer_id, payload.path)
    except (OSError, PeerError, http.client.HTTPException) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=msg)
    return {"success": True, "name": msg}


@router.post("/{peer_id}/sync")
async def sync_peer(peer_id: str, request: Request,
                    principal: Principal = Depends(require_permission("write"))):
    app = _app(request)
    for sid in app.config.shares():
        app.engine.request_sync(sid, peer_id)
    return {"success": True}