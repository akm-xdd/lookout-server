# app/services/notification_trigger.py
from typing import Dict, Any, Optional
from uuid import UUID
from supabase import Client

from app.db.supabase import get_supabase_admin
from app.services.outage_notification_service import outage_notification_service


class NotificationTrigger:
    """
    Simple bridge between monitoring and notification system.
    Determines when endpoint failures should trigger outage notifications.
    """
    
    def __init__(self):
        self.supabase: Client = get_supabase_admin()
    
    async def handle_endpoint_check(self, endpoint_id: str, check_result: Dict[str, Any]) -> None:
        """
        Process endpoint check result and trigger notifications if needed.
        Called after each monitoring check is completed and saved.
        """
        
        try:
            # Only process failures - successes don't trigger notifications
            if check_result.get('success', False):
                return
            
            # Get endpoint data with user info
            endpoint_data = await self._get_endpoint_with_user_data(endpoint_id)
            
            if not endpoint_data:
                return
            
            # Get user notification settings
            user_settings = await self._get_user_notification_settings(endpoint_data['user_id'])
            
            if not user_settings:
                return
            
            # Check if failure meets threshold and user has notifications enabled
            consecutive_failures = endpoint_data.get('consecutive_failures', 0)
            failure_threshold = user_settings.get('failure_threshold', 5)
            notifications_enabled = user_settings.get('email_notifications_enabled', False)
            
            if not notifications_enabled:
                return
            
            if consecutive_failures >= failure_threshold:
                # Trigger outage notification system
                await outage_notification_service.handle_endpoint_failure(
                    user_id=endpoint_data['user_id'],
                    endpoint_id=endpoint_id,
                    failure_threshold=failure_threshold,
                    consecutive_failures=consecutive_failures
                )
                
                print(f"🚨 Triggered outage notification for endpoint {endpoint_id} (failures: {consecutive_failures}/{failure_threshold})")
            
        except Exception as e:
            print(f"❌ Error in notification trigger: {str(e)}")
    
    async def _get_endpoint_with_user_data(self, endpoint_id: str) -> Optional[Dict[str, Any]]:
        """Get endpoint data with user information"""
        
        try:
            response = self.supabase.table("endpoints").select(
                "id, consecutive_failures, workspaces!inner(user_id)"
            ).eq("id", endpoint_id).execute()
            
            if not response.data:
                return None
            
            endpoint = response.data[0]
            
            return {
                'id': endpoint['id'],
                'consecutive_failures': endpoint.get('consecutive_failures', 0),
                'user_id': endpoint['workspaces']['user_id']
            }
            
        except Exception as e:
            print(f"❌ Error getting endpoint data: {str(e)}")
            return None
    
    async def _get_user_notification_settings(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user notification preferences"""
        
        try:
            response = self.supabase.table("user_notification_settings").select(
                "email_notifications_enabled, failure_threshold"
            ).eq("user_id", user_id).execute()
            
            return response.data[0] if response.data else None
            
        except Exception as e:
            print(f"❌ Error getting user notification settings: {str(e)}")
            return None


# Singleton trigger instance
notification_trigger = NotificationTrigger()