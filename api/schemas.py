from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# Request Schemas
class SessionCreate(BaseModel):
    target_url: str = Field(..., description="Target URL for CTF challenge")
    goal: Optional[str] = Field(None, description="Optional goal description")


class ChatMessage(BaseModel):
    session_id: Optional[int] = Field(None, description="Optional session ID to associate with")
    message: str = Field(..., description="Message content from Antigravity")


# Response Schemas
class SessionResponse(BaseModel):
    id: int
    target_url: str
    goal: Optional[str]
    status: SessionStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    id: int
    session_id: Optional[int]
    role: MessageRole
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_results: Optional[List[Dict[str, Any]]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class FindingResponse(BaseModel):
    id: int
    session_id: int
    finding_type: str
    description: str
    location: Optional[str]
    evidence: Optional[Dict[str, Any]]
    created_at: datetime

    class Config:
        from_attributes = True


class FlagResponse(BaseModel):
    id: int
    session_id: int
    flag_value: str
    context: Optional[str]
    discovered_at: datetime

    class Config:
        from_attributes = True


class ChatResponse(BaseModel):
    conversation_id: int
    role: MessageRole
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    findings: Optional[List[FindingResponse]] = None
    flags: Optional[List[FlagResponse]] = None


class HealthResponse(BaseModel):
    status: str
    database: str
    vertex_ai: str
