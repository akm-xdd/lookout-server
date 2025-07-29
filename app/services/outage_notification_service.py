# app/services/outage_notification_service.py
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from uuid import UUID
from supabase import Client

from app.db.supabase import get_supabase_admin
from app.services.email_client import BrevoEmailClient
from app.core.email_config import email_settings, validate_email_config


class OutageNotificationService:
    """
    Simplified outage notification system:
    1. First outage → Start 15-minute buffer
    2. Collect all failures across all workspaces
    3. Send one email after 15 minutes
    4. Enter escalating cooldown (1hr→2hr→3hr→5hr→8hr cycle)
    5. During cooldown: complete silence
    """
    
    def __init__(self):
        self.supabase: Client = get_supabase_admin()
        self.email_client = BrevoEmailClient()
        self.is_running = False
        self.check_interval = 60  # Check every 1 minute
    
    async def start(self) -> None:
        """Start the notification service"""
        
        if not validate_email_config():
            print("❌ Email configuration invalid, notification service not started")
            return
        
        print("📧 Starting Outage Notification Service...")
        print(f"🔄 Check interval: {self.check_interval} seconds")
        
        self.is_running = True
        
        try:
            await self._notification_loop()
        except Exception as e:
            print(f"❌ Notification service crashed: {str(e)}")
        finally:
            self.is_running = False
            print("📧 Outage Notification Service stopped")
    
    async def stop(self) -> None:
        """Stop the notification service"""
        print("🛑 Stopping Outage Notification Service...")
        self.is_running = False
    
    async def handle_endpoint_failure(self, user_id: str, endpoint_id: str, failure_threshold: int, consecutive_failures: int) -> None:
        """
        Handle endpoint failure - called by monitoring integration
        Only processes if failure hits threshold and user has notifications enabled
        """
        
        if consecutive_failures < failure_threshold:
            return
        
        try:
            # Get or create global email state for user
            email_state = await self._get_or_create_email_state(user_id)
            
            # Check if we're in cooldown - if so, ignore completely
            if await self._is_in_cooldown(email_state):
                print(f"⏭️ User {user_id} in cooldown, ignoring endpoint {endpoint_id} failure")
                return
            
            # If no active buffer, start one
            if not email_state.get('buffer_active'):
                await self._start_buffer_window(user_id, endpoint_id)
                print(f"🚨 Started 15-minute buffer for user {user_id}")
            else:
                # Add to existing buffer
                await self._add_to_buffer(user_id, endpoint_id)
                print(f"📍 Added endpoint {endpoint_id} to buffer for user {user_id}")
            
        except Exception as e:
            print(f"❌ Error handling endpoint failure: {str(e)}")
    
    async def _notification_loop(self) -> None:
        """Main loop - checks for expired buffers and cooldowns"""
        
        while self.is_running:
            try:
                current_time = datetime.now()
                
                # Process expired buffer windows (15 minutes old)
                await self._process_expired_buffers(current_time)
                
                # Clean up expired cooldowns (reset to ready state)
                await self._cleanup_expired_cooldowns(current_time)
                
            except Exception as e:
                print(f"❌ Error in notification loop: {str(e)}")
            
            await asyncio.sleep(self.check_interval)
    
    async def _process_expired_buffers(self, current_time: datetime) -> None:
        """Find and process buffer windows that have expired (15+ minutes old)"""
        
        try:
            # Find active buffers older than 15 minutes
            cutoff_time = current_time - timedelta(minutes=15)
            
            response = self.supabase.table("global_email_state").select("*").eq(
                "buffer_active", True
            ).lt("buffer_started_at", cutoff_time.isoformat()).execute()
            
            expired_buffers = response.data or []
            
            if expired_buffers:
                print(f"📬 Found {len(expired_buffers)} expired buffers")
                
                for buffer in expired_buffers:
                    await self._send_buffer_notification(buffer)
            
        except Exception as e:
            print(f"❌ Error processing expired buffers: {str(e)}")
    
    async def _cleanup_expired_cooldowns(self, current_time: datetime) -> None:
        """Reset users whose cooldown period has expired"""
        
        try:
            # Find users whose cooldown has expired
            response = self.supabase.table("global_email_state").select("user_id").lt(
                "cooldown_expires_at", current_time.isoformat()
            ).execute()
            
            expired_cooldowns = response.data or []
            
            for cooldown in expired_cooldowns:
                user_id = cooldown['user_id']
                
                # Reset to ready state
                await self._reset_user_to_ready_state(user_id)
                print(f"✅ Reset user {user_id} cooldown - ready for new outages")
            
        except Exception as e:
            print(f"❌ Error cleaning up expired cooldowns: {str(e)}")
    
    async def _send_buffer_notification(self, buffer_state: Dict[str, Any]) -> None:
        """Send notification email for expired buffer and start cooldown"""
        
        user_id = buffer_state['user_id']
        failing_endpoint_ids = buffer_state.get('failing_endpoint_ids', [])
        
        try:
            # Get user notification settings
            user_settings = await self._get_user_notification_settings(user_id)
            
            if not user_settings or not user_settings.get('email_notifications_enabled'):
                print(f"⏭️ User {user_id} has notifications disabled, skipping email")
                await self._reset_user_to_ready_state(user_id)
                return
            
            # Get endpoint details for email
            endpoint_details = await self._get_endpoint_details(failing_endpoint_ids)
            
            if not endpoint_details:
                print(f"❌ No valid endpoint details found for user {user_id}")
                await self._reset_user_to_ready_state(user_id)
                return
            
            # Send notification email
            success = await self._send_outage_email(user_settings, endpoint_details)
            
            if success:
                # Record in history and start cooldown
                await self._record_notification_and_start_cooldown(
                    user_id, failing_endpoint_ids, buffer_state.get('cooldown_level', 0)
                )
                print(f"✅ Sent outage notification to {user_settings['notification_email']}")
            else:
                print(f"❌ Failed to send email for user {user_id}")
                # Reset to ready state on email failure
                await self._reset_user_to_ready_state(user_id)
            
        except Exception as e:
            print(f"❌ Error sending buffer notification: {str(e)}")
            await self._reset_user_to_ready_state(user_id)
    
    async def _get_or_create_email_state(self, user_id: str) -> Dict[str, Any]:
        """Get user's email state, create if doesn't exist"""
        
        try:
            # Try to get existing state
            response = self.supabase.table("global_email_state").select("*").eq(
                "user_id", user_id
            ).execute()
            
            if response.data:
                return response.data[0]
            
            # Create new state
            new_state = {
                "user_id": user_id,
                "buffer_active": False,
                "cooldown_level": 0
            }
            
            create_response = self.supabase.table("global_email_state").insert(new_state).execute()
            
            return create_response.data[0] if create_response.data else new_state
            
        except Exception as e:
            print(f"❌ Error getting/creating email state: {str(e)}")
            return {"user_id": user_id, "buffer_active": False, "cooldown_level": 0}
    
    async def _is_in_cooldown(self, email_state: Dict[str, Any]) -> bool:
        """Check if user is currently in cooldown period"""
        
        cooldown_expires_at = email_state.get('cooldown_expires_at')
        
        if not cooldown_expires_at:
            return False
        
        try:
            # Parse the datetime from database (it's timezone-aware)
            expires_at = datetime.fromisoformat(cooldown_expires_at.replace('Z', '+00:00'))
            
            # Get current time as timezone-aware UTC
            from datetime import timezone
            current_time = datetime.now(timezone.utc)
            
            in_cooldown = current_time < expires_at
            
            print(f"🔍 DEBUG: Current: {current_time}, Expires: {expires_at}, In cooldown: {in_cooldown}")
            return in_cooldown
            
        except Exception as e:
            print(f"❌ Error checking cooldown: {str(e)}")
            return False
    
    async def _start_buffer_window(self, user_id: str, endpoint_id: str) -> None:
        """Start 15-minute buffer window for collecting failures"""
        
        try:
            update_data = {
                "buffer_active": True,
                "buffer_started_at": datetime.now().isoformat(),
                "failing_endpoint_ids": [endpoint_id],
                "updated_at": datetime.now().isoformat()
            }
            
            self.supabase.table("global_email_state").update(update_data).eq(
                "user_id", user_id
            ).execute()
            
        except Exception as e:
            print(f"❌ Error starting buffer window: {str(e)}")
    
    async def _add_to_buffer(self, user_id: str, endpoint_id: str) -> None:
        """Add endpoint to existing buffer window"""
        
        try:
            # Get current state
            response = self.supabase.table("global_email_state").select("failing_endpoint_ids").eq(
                "user_id", user_id
            ).execute()
            
            if not response.data:
                return
            
            current_endpoints = response.data[0].get('failing_endpoint_ids', [])
            
            # Add if not already present
            if endpoint_id not in current_endpoints:
                current_endpoints.append(endpoint_id)
                
                self.supabase.table("global_email_state").update({
                    "failing_endpoint_ids": current_endpoints,
                    "updated_at": datetime.now().isoformat()
                }).eq("user_id", user_id).execute()
            
        except Exception as e:
            print(f"❌ Error adding to buffer: {str(e)}")
    
    async def _get_user_notification_settings(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user notification settings"""
        
        try:
            response = self.supabase.table("user_notification_settings").select("*").eq(
                "user_id", user_id
            ).execute()
            
            return response.data[0] if response.data else None
            
        except Exception as e:
            print(f"❌ Error getting user settings: {str(e)}")
            return None
    
    async def _get_endpoint_details(self, endpoint_ids: List[str]) -> List[Dict[str, Any]]:
        """Get endpoint details with workspace names"""
        
        if not endpoint_ids:
            return []
        
        try:
            response = self.supabase.table("endpoints").select(
                "id, name, consecutive_failures, last_check_at, workspaces!inner(name)"
            ).in_("id", endpoint_ids).execute()
            
            # Flatten workspace names
            details = []
            for endpoint in response.data or []:
                details.append({
                    'id': endpoint['id'],
                    'name': endpoint['name'],
                    'consecutive_failures': endpoint.get('consecutive_failures', 0),
                    'last_check_at': endpoint.get('last_check_at'),
                    'workspace_name': endpoint['workspaces']['name']
                })
            
            return details
            
        except Exception as e:
            print(f"❌ Error getting endpoint details: {str(e)}")
            return []
    
    async def _send_outage_email(self, user_settings: Dict[str, Any], endpoint_details: List[Dict[str, Any]]) -> bool:
        """Send outage notification email"""
        
        try:
            dashboard_link = f"{email_settings.dashboard_base_url}/dashboard"
            
            return await self.email_client.send_outage_notification(
                to_email=user_settings['notification_email'],
                workspace_name="Multiple Workspaces" if len(set(ep['workspace_name'] for ep in endpoint_details)) > 1 else endpoint_details[0]['workspace_name'],
                failing_endpoints=endpoint_details,
                dashboard_link=dashboard_link
            )
            
        except Exception as e:
            print(f"❌ Error sending outage email: {str(e)}")
            return False
    
    async def _record_notification_and_start_cooldown(self, user_id: str, endpoint_ids: List[str], current_cooldown_level: int) -> None:
        """Record notification in history and start appropriate cooldown"""
        
        try:
            # Record in history
            history_data = {
                "user_id": user_id,
                "endpoint_ids": endpoint_ids,
                "endpoint_count": len(endpoint_ids),
                "cooldown_level_used": current_cooldown_level
            }
            
            self.supabase.table("notification_history").insert(history_data).execute()
            
            # Calculate next cooldown level and duration
            next_cooldown_level, cooldown_hours = self._get_next_cooldown(current_cooldown_level)
            cooldown_expires_at = datetime.now() + timedelta(hours=cooldown_hours)
            
            # Update email state with cooldown
            update_data = {
                "buffer_active": False,
                "buffer_started_at": None,
                "failing_endpoint_ids": [],
                "cooldown_level": next_cooldown_level,
                "cooldown_expires_at": cooldown_expires_at.isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            
            self.supabase.table("global_email_state").update(update_data).eq(
                "user_id", user_id
            ).execute()
            
            print(f"🔄 User {user_id} entered {cooldown_hours}hr cooldown (level {next_cooldown_level})")
            
        except Exception as e:
            print(f"❌ Error recording notification and starting cooldown: {str(e)}")
    
    async def _reset_user_to_ready_state(self, user_id: str) -> None:
        """Reset user to ready state (no buffer, no cooldown)"""
        
        try:
            reset_data = {
                "buffer_active": False,
                "buffer_started_at": None,  
                "failing_endpoint_ids": [],
                "cooldown_level": 0,
                "cooldown_expires_at": None,
                "updated_at": datetime.now().isoformat()
            }
            
            self.supabase.table("global_email_state").update(reset_data).eq(
                "user_id", user_id
            ).execute()
            
        except Exception as e:
            print(f"❌ Error resetting user to ready state: {str(e)}")
    
    def _get_next_cooldown(self, current_level: int) -> tuple[int, int]:
        """
        Get next cooldown level and hours
        Cycle: 0→1(1hr)→2(2hr)→3(3hr)→4(5hr)→1(1hr)→2(2hr)...
        """
        
        cooldown_map = {
            0: (1, 1),   # Ready → 1hr cooldown
            1: (2, 2),   # 1hr → 2hr cooldown  
            2: (3, 3),   # 2hr → 3hr cooldown
            3: (4, 5),   # 3hr → 5hr cooldown
            4: (1, 1),   # 5hr → back to 1hr cooldown (8hr was the max)
        }
        
        return cooldown_map.get(current_level, (1, 1))


# Singleton service instance
outage_notification_service = OutageNotificationService()