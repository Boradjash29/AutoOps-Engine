# FILE: api/models.py
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class HealthResponse(BaseModel):
    cpu: float
    ram: float
    disk: float
    uptime_hours: float
    net_sent_mb: float
    net_recv_mb: float
    timestamp: str

class ContainerResponse(BaseModel):
    name: str
    status: str
    image: str
    id: str
    created: str

class RestartResponse(BaseModel):
    message: str
    success: bool

class TestAlertResponse(BaseModel):
    sent: bool

class CleanupPreviewResponse(BaseModel):
    dangling_images: int
    stopped_containers: int
    estimated_mb: float

class ServerCreate(BaseModel):
    name: str
    host: str
    port: int = 22
    username: str
    ssh_key_path: Optional[str] = None
    password: Optional[str] = None


