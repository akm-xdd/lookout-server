# app/core/config.py
import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import validator
from dotenv import load_dotenv

load_dotenv() 


class Settings(BaseSettings):
    # Supabase Configuration
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_key: str = os.getenv("SUPABASE_SERVICE_KEY", "")
    supabase_anon_key: str = os.getenv("SUPABASE_ANON_KEY", "")
    
    # API Configuration
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT", "8000"))
    debug: bool = os.getenv("DEBUG", "False").lower() == "true"
    
    # Project Configuration
    project_name: str = "LookOut API"
    project_version: str = "1.0.0"
    
    # NEW: Scheduler Configuration
    scheduler_enabled: bool = os.getenv("SCHEDULER_ENABLED", "True").lower() == "true"
    scheduler_interval: int = int(os.getenv("SCHEDULER_INTERVAL", "30"))  # seconds
    health_check_interval: int = int(os.getenv("HEALTH_CHECK_INTERVAL", "120"))  # seconds
    worker_count: int = int(os.getenv("WORKER_COUNT", "12"))
    http_timeout: int = int(os.getenv("HTTP_TIMEOUT", "20"))  # seconds
    retry_delay: int = int(os.getenv("RETRY_DELAY", "10"))  # seconds
    
    # NEW: Circuit Breaker Configuration
    failure_threshold: int = int(os.getenv("FAILURE_THRESHOLD", "3"))
    success_threshold: int = int(os.getenv("SUCCESS_THRESHOLD", "3"))
    queue_overwhelmed_size: int = int(os.getenv("QUEUE_OVERWHELMED_SIZE", "1000"))
    
    # NEW: Monitoring Configuration
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    cache_warning_size: int = int(os.getenv("CACHE_WARNING_SIZE", "5000"))
    queue_warning_size: int = int(os.getenv("QUEUE_WARNING_SIZE", "500"))
    
    # NEW: Optional External Monitoring
    sentry_dsn: Optional[str] = os.getenv("SENTRY_DSN")
    
    @validator("supabase_url")
    def validate_supabase_url(cls, v):
        if not v:
            raise ValueError("SUPABASE_URL is required")
        return v
    
    @validator("supabase_service_key") 
    def validate_supabase_service_key(cls, v):
        if not v:
            raise ValueError("SUPABASE_SERVICE_KEY is required")
        return v
    
    @validator("worker_count")
    def validate_worker_count(cls, v):
        if v < 1 or v > 50:
            raise ValueError("WORKER_COUNT must be between 1 and 50")
        return v
    
    @validator("scheduler_interval")
    def validate_scheduler_interval(cls, v):
        if v < 10 or v > 300:
            raise ValueError("SCHEDULER_INTERVAL must be between 10 and 300 seconds")
        return v
    
    @validator("http_timeout")
    def validate_http_timeout(cls, v):
        if v < 5 or v > 120:
            raise ValueError("HTTP_TIMEOUT must be between 5 and 120 seconds")
        return v

    class Config:
        env_file = ".env"
        extra = "ignore" 


settings = Settings()


def get_cors_origins() -> list[str]:
    """Parse CORS origins from environment variable"""
    cors_env = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    
    # Remove any array brackets and quotes
    cors_env = cors_env.strip().strip('[]').replace('"', '').replace("'", "")
    
    # Split by comma and clean
    origins = [origin.strip().rstrip('/') for origin in cors_env.split(',')]
    
    # Filter empty and return
    return [origin for origin in origins if origin]