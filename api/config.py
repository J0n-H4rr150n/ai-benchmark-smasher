import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings"""
    
    # Database
    database_url: str = "postgresql+asyncpg://ctf:ctf_password_change_in_prod@localhost:5432/ctf_smasher"
    
    # GCP / Vertex AI
    gcp_project_id: str
    google_application_credentials: str = "./vertex-executor-key.json"
    gemini_model: str = "gemini-2.5-pro"  # or gemini-2.5-pro
    gemini_location: str = "us-central1"
    
    # Playwright
    playwright_state_dir: str = "/app/.playwright"
    
    # App
    debug: bool = True
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
