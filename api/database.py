from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
import os
import logging

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://ctf:ctf_password_change_in_prod@localhost:5432/ctf_smasher")

SQLALCHEMY_ECHO = os.getenv("SQLALCHEMY_ECHO", "0").strip().lower() in {"1", "true", "yes", "y"}

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=SQLALCHEMY_ECHO,
    poolclass=NullPool,  # For development; use proper pooling in production
)

# If echo is disabled, keep SQLAlchemy engine logs quiet.
if not SQLALCHEMY_ECHO:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Base class for models
Base = declarative_base()


async def get_db():
    """Dependency for FastAPI to get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database tables"""
    async with engine.begin() as conn:
        # Enable pgvector extension
        from sqlalchemy import text
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
        
        # Manual migrations
        try:
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS step_number INTEGER"))
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS llm_analysis TEXT"))
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS llm_findings TEXT"))
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS llm_ideas TEXT"))
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS llm_next_steps TEXT"))
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS llm_need_block TEXT"))
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS llm_decision TEXT"))
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS llm_critique TEXT"))
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS llm_confidence_score TEXT"))
            await conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS llm_grading_score TEXT"))
        except Exception:
            # Table might not exist yet if it's the very first run
            pass
