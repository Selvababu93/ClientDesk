import uvicorn
import json, os, asyncio
from datetime import datetime
from typing import Dict, Set
from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from redis import Redis

from .db import Base, engine, get_db
from .models import Device, Metric, Command
from .schemas import RegisterReq, RegisterResp, MetricIn, CommandCreate, CommandOut, CommandUpdate, DeviceResp
from .auth import gen_token, require_agent, require_admin, get_agent_by_hostname
from .utils import maybe_alert

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Mini RMM")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_headers=["*"], allow_methods=["*"])

redis = Redis(host=os.getenv("REDIS_HOST","redis"), port=6379, decode_responses=True)

# --- in-memory WS registry: device_id -> websocket ---
agent_ws: Dict[int, WebSocket] = {}

@app.get("/admin/login")
def admin_login(authorization: str | None= Header(None)):
    # will raise 401 automayically if invalid
    require_admin(authorization)
    return{"status" : "ok", "message" : "Admin token valid"}

@app.post("/register", response_model =RegisterResp)
def  register(req: RegisterReq, db: Session = Depends(get_db)):
    existing_device = get_agent_by_hostname(db, req.hostname)
    if existing_device:
        print(f"Device found : {str(existing_device)}")
        return DeviceResp.from_orm(existing_device)
    else:
        token = gen_token()
        new_device = Device(hostname=req.hostname, os=req.os, arch=req.arch,
                            agent_version= req.agent_version, token=token,
                            last_seen=datetime.utcnow(), online=False)
        db.add(new_device); db.commit(); db.refresh(new_device)
        return RegisterResp.model_validate(new_device)


@app.post("/metrics")
def metrics(m: MetricIn, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    dev = require_agent(db, authorization)
    dev.last_seen = datetime.utcnow(); dev.online = True
    row = Metric(device_id=dev.id, cpu=m.cpu, mem=m.mem, disk=m.disk,
                 uptime_sec=m.uptime_sec, battery_pct=m.battery_pct,
                 details=json.dumps(m.details or {}))
    db.add(row); db.commit()
    maybe_alert(dev, row)
    return {"ok": True}

@app.post("/heartbeat")
def heartbeat(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    dev = require_agent(db, authorization)
    dev.last_seen = datetime.utcnow(); dev.online = True
    db.commit()
    return {"ok": True}

@app.post("/devices/{device_id}/commands", response_model=CommandOut)
def create_command(device_id: int, body: CommandCreate, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    require_admin(authorization)
    cmd = Command(device_id=device_id, kind=body.kind, payload=body.payload or "")
    db.add(cmd); db.commit(); db.refresh(cmd)
    # notify via Redis (dashboards) and try WS push to agent
    redis.publish("commands", json.dumps({"device_id": device_id, "cmd_id": cmd.id}))
    ws = agent_ws.get(device_id)
    if ws:
        try: asyncio.create_task(ws.send_text(json.dumps({"cmd_id": cmd.id, "kind": cmd.kind, "payload": cmd.payload})))
        except Exception: pass
    return CommandOut(id=cmd.id, kind=cmd.kind, payload=cmd.payload or None)

@app.post("/commands/{cmd_id}/status")
def command_status(cmd_id: int, body: CommandUpdate, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    dev = require_agent(db, authorization)
    cmd = db.query(Command).filter(Command.id==cmd_id, Command.device_id==dev.id).first()
    if not cmd: raise HTTPException(404, "Command not found")
    cmd.status = body.status; cmd.result = body.result
    db.commit()
    return {"ok": True}

@app.get("/devices")
def list_devices(authorization: str | None = Header(None), db: Session = Depends(get_db)):
    require_admin(authorization)
    q = db.query(Device).all()
    return [{"id":d.id,"hostname":d.hostname,"os":d.os,"arch":d.arch,"online":d.online,"last_seen":d.last_seen.isoformat()} for d in q]

@app.websocket("/ws/agent/{device_id}")
async def ws_agent(websocket: WebSocket, device_id: int):
    await websocket.accept()
    agent_ws[device_id] = websocket
    try:
        while True:
            msg = await websocket.receive_text()  # agents may send logs/status
            # (Optional: forward to Redis or store)
    except WebSocketDisconnect:
        agent_ws.pop(device_id, None)


    