from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from pgvector.sqlalchemy import Vector

from .database import Base


class SessionStatus(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class CTFSession(Base):
    """CTF solving session"""
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    target_url = Column(String, nullable=False)
    goal = Column(Text, nullable=True)
    status = Column(SQLEnum(SessionStatus), default=SessionStatus.ACTIVE)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    conversations = relationship("Conversation", back_populates="session", cascade="all, delete-orphan")
    findings = relationship("Finding", back_populates="session", cascade="all, delete-orphan")
    flags = relationship("Flag", back_populates="session", cascade="all, delete-orphan")


class Conversation(Base):
    """Conversation messages between Antigravity and Gemini"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=True, index=True)
    role = Column(SQLEnum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)
    tool_calls = Column(JSON, nullable=True)  # Store tool calls made by Gemini
    tool_results = Column(JSON, nullable=True)  # Store results from tool execution
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    session = relationship("CTFSession", back_populates="conversations")


class Finding(Base):
    """Analysis findings (vulnerabilities, interesting patterns, etc.)"""
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False, index=True)
    finding_type = Column(String, nullable=False)  # e.g., "sql_injection", "hidden_form", etc.
    description = Column(Text, nullable=False)
    location = Column(String, nullable=True)  # URL or selector where found
    evidence = Column(JSON, nullable=True)  # Supporting evidence
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    session = relationship("CTFSession", back_populates="findings")


class Flag(Base):
    """Discovered CTF flags"""
    __tablename__ = "flags"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False, index=True)
    flag_value = Column(String, nullable=False, unique=True)
    context = Column(Text, nullable=True)  # Where/how it was found
    discovered_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    session = relationship("CTFSession", back_populates="flags")


class Embedding(Base):
    """Vector embeddings for semantic search"""
    __tablename__ = "embeddings"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(768), nullable=False)  # Gemini text-embedding-004 is 768 dims
    meta_data = Column(JSON, nullable=True)  # Renamed from metadata to avoid SQLAlchemy conflict
    created_at = Column(DateTime, default=datetime.utcnow)
