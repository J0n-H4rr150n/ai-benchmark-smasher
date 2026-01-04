from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from .database import init_db
from .routers import sessions, chat
from .tools.registry import tool_registry
from . import schemas


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle management for the application"""
    # Startup
    await init_db()
    print("Database initialized")
    
    yield
    
    # Shutdown
    await tool_registry.cleanup_all()
    print("Tools cleaned up")


app = FastAPI(
    title="AI Benchmark Smasher",
    description="AI-powered CTF challenge solver using Gemini 2.5",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(sessions.router)
app.include_router(chat.router)


@app.get("/health", response_model=schemas.HealthResponse)
async def health_check():
    """Health check endpoint"""
    return schemas.HealthResponse(
        status="healthy",
        database="connected",
        vertex_ai="ready"
    )


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "AI Benchmark Smasher API",
        "version": "1.0.0",
        "docs": "/docs"
    }
