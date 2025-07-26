# app/services/email_template_service.py
import os
from pathlib import Path
from typing import Dict, Any
from jinja2 import Environment, FileSystemLoader, select_autoescape


class EmailTemplateService:
    """Service for loading and rendering email templates"""
    
    def __init__(self):
        # Get template directory path
        self.template_dir = Path(__file__).parent.parent / "templates" / "emails"
        
        # Initialize Jinja2 environment
        self.env = Environment(
            loader=FileSystemLoader(self.template_dir),
            autoescape=select_autoescape(['html', 'xml'])
        )
    
    def render_outage_notification(
        self,
        workspace_name: str,
        failing_endpoints: list,
        dashboard_link: str
    ) -> tuple[str, str]:
        """
        Render outage notification email templates
        Returns: (html_content, text_content)
        """
        
        context = {
            'workspace_name': workspace_name,
            'failing_endpoints': failing_endpoints,
            'dashboard_link': dashboard_link,
            'endpoint_count': len(failing_endpoints)
        }
        
        # Render HTML template
        html_template = self.env.get_template('outage_notification.html')
        html_content = html_template.render(**context)
        
        # Render text template
        text_template = self.env.get_template('outage_notification.txt')
        text_content = text_template.render(**context)
        
        return html_content, text_content
    
    def get_subject_line(self, workspace_name: str, endpoint_count: int) -> str:
        """Generate email subject line"""
        if endpoint_count == 1:
            return f"[LookOut Alert] 1 endpoint down in \"{workspace_name}\""
        else:
            return f"[LookOut Alert] {endpoint_count} endpoints down in \"{workspace_name}\""