# app/services/email_client.py
import aiohttp
import json
from typing import Dict, Any, Optional
from app.core.email_config import email_settings
from app.services.email_template_service import EmailTemplateService


class BrevoEmailClient:
    """Simple async Brevo email client"""
    
    def __init__(self):
        self.api_key = email_settings.brevo_api_key
        self.api_url = email_settings.brevo_api_url
        self.sender_email = email_settings.sender_email
        self.sender_name = email_settings.sender_name
        self.test_mode = email_settings.test_mode
        self.template_service = EmailTemplateService()
    
    async def send_email(
        self, 
        to_email: str, 
        subject: str, 
        html_content: str,
        text_content: Optional[str] = None
    ) -> bool:
        """Send email via Brevo API"""
        
        if self.test_mode:
            print(f"\n📧 TEST MODE - Email would be sent:")
            print(f"To: {to_email}")
            print(f"Subject: {subject}")
            print(f"Content: {text_content or html_content[:100]}...")
            return True
        
        payload = {
            "sender": {
                "name": self.sender_name,
                "email": self.sender_email
            },
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html_content
        }
        
        if text_content:
            payload["textContent"] = text_content
        
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": self.api_key
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url,
                    headers=headers,
                    data=json.dumps(payload),
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    
                    if response.status == 201:
                        print(f"✅ Email sent successfully to {to_email}")
                        return True
                    else:
                        error_text = await response.text()
                        print(f"❌ Failed to send email to {to_email}: {response.status} - {error_text}")
                        return False
                        
        except Exception as e:
            print(f"❌ Email sending error: {str(e)}")
            return False
    
    async def send_outage_notification(
        self,
        to_email: str,
        workspace_name: str,
        failing_endpoints: list,
        dashboard_link: str
    ) -> bool:
        """Send outage notification email"""
        
        # Generate subject and content using templates
        subject = self.template_service.get_subject_line(workspace_name, len(failing_endpoints))
        html_content, text_content = self.template_service.render_outage_notification(
            workspace_name, failing_endpoints, dashboard_link
        )
        
        return await self.send_email(to_email, subject, html_content, text_content)