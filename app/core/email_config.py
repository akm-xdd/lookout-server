# app/core/email_config.py
import os
from typing import Optional
from pydantic_settings import BaseSettings


class EmailSettings(BaseSettings):
    """Email configuration settings"""
    
    # Brevo configuration
    brevo_api_key: str = os.getenv("BREVO_API_KEY", "")
    brevo_api_url: str = "https://api.brevo.com/v3/smtp/email"
    
    # Sender configuration  
    sender_email: str = os.getenv("SENDER_EMAIL", "noreply@lookoutapi.xyz")
    sender_name: str = os.getenv("SENDER_NAME", "LookOut Monitoring")
    
    # Email settings
    test_mode: bool = os.getenv("EMAIL_TEST_MODE", "False").lower() == "true"
    dashboard_base_url: str = os.getenv("DASHBOARD_BASE_URL", "https://lookoutapi.xyz/dashboard")
    
    class Config:
        env_file = ".env"
        extra = "ignore"  # Ignore extra environment variables


# Global email settings instance
email_settings = EmailSettings()


# Validation helper
def validate_email_config() -> bool:
    """Validate email configuration is properly set"""
    if not email_settings.brevo_api_key:
        print("❌ BREVO_API_KEY not set")
        return False
    
    if not email_settings.sender_email:
        print("❌ SENDER_EMAIL not set")
        return False
    
    if email_settings.test_mode:
        print("📧 Email service running in TEST MODE - emails will be logged, not sent")
    
    return True