import os, secrets
from fastapi import Header, HTTPException
from sqlalchemy.orm import Session
from .models import Device
from dotenv import load_dotenv
load_dotenv()


ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "your_super_secret_admin_token")
if not ADMIN_TOKEN:
    raise RuntimeError("ADMIN_TOKEN not set in environment")


def gen_token() -> str:
    return secrets.token_urlsafe(32)

def require_agent(db: Session, authorization: str | None) -> Device:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Unauthorized")
    tok = authorization.removeprefix("Bearer ").strip()
    dev = db.query(Device).filter(Device.token == tok).first()
    if not dev:
        raise HTTPException(401, "Invalid token")
    return dev

def require_admin(authorization: str | None):
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(401, "Admin token invalid")
