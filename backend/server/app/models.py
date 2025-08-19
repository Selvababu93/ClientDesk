from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from .db import Base

class Device(Base):
    __tablename__ = "devices"
    id = Column(Integer, primary_key=True)
    hostname = Column(String, index=True)
    os = Column(String)
    arch = Column(String)
    agent_version = Column(String)
    token = Column(String, unique=True, index=True)
    last_seen = Column(DateTime, default=datetime.utcnow)
    online = Column(Boolean, default=False)

    metrics = relationship("Metric", back_populates="device", cascade="all,delete")

class Metric(Base):
    __tablename__ = "metrics"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    cpu = Column(Float)
    mem = Column(Float)
    disk = Column(Float)
    uptime_sec = Column(Float)
    battery_pct = Column(Float, nullable=True)
    details = Column(Text, nullable=True)  # optional JSON string

    device = relationship("Device", back_populates="metrics")

class Command(Base):
    __tablename__ = "commands"
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"), index=True)
    created = Column(DateTime, default=datetime.utcnow)
    kind = Column(String)       # 'shell' | 'restart' | 'shutdown' | 'script'
    payload = Column(Text)      # JSON or script text
    status = Column(String, default="queued")  # queued|sent|ack|done|error
    result = Column(Text, nullable=True)
