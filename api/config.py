import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings"""
    
    # Database
    database_url: str = "postgresql+asyncpg://ctf:ctf_password_change_in_prod@localhost:5432/ctf_smasher"
    
    # GCP / Vertex AI
    gcp_project_id: str
    google_application_credentials: str = "./vertex-executor-key.json"
    gemini_model: str = "gemini-2.5-flash"  # or gemini-2.5-pro
    gemini_location: str = "us-central1"

    # Embeddings (pgvector knowledge base)
    # Vertex AI text embedding model; should output 768-dim vectors to match DB schema.
    embedding_model: str = "textembedding-gecko@003"
    # Which embedding backend to use:
    # - "kaggle_tfhub": Universal Sentence Encoder via TF-Hub Kaggle URLs
    # - "vertexai": Vertex AI text embeddings
    # - "hash": deterministic local hash embedding (no external calls)
    # - "auto": try kaggle_tfhub, then vertexai, then hash
    embedding_provider: str = "kaggle_tfhub"
    # If true, do not fall back; raise when the chosen provider fails.
    embedding_strict: bool = True
    
    # Playwright
    playwright_state_dir: str = "/app/.playwright"
    playwright_headless: bool = True
    playwright_slow_mo_ms: int = 0
    playwright_devtools: bool = False
    
    # App
    debug: bool = True
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
