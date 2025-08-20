from pydantic import BaseModel
from typing import Optional, Any, Dict, List

class RegisterReq(BaseModel):
    hostname: str
    os: str
    arch: str
    agent_version: str

class RegisterResp(BaseModel):
    id: int
    token: str

    class Config:
        from_attributes = True
   
class MetricIn(BaseModel):
    cpu: float
    mem: float
    disk: float
    uptime_sec: float
    battery_pct: Optional[float] = None
    details: Optional[Dict[str, Any]] = None

class CommandCreate(BaseModel):
    kind: str
    payload: Optional[str] = None

class CommandOut(BaseModel):
    id: int
    kind: str
    payload: Optional[str] = None

class CommandUpdate(BaseModel):
    status: str
    result: Optional[str] = None


# This is to avoid register again and agian for same device in db
class DeviceResp(BaseModel):
    id : int
    token : str

    class Config:
        from_attributes = True