# app/services/notification_settings_service.py
from typing import Optional
from uuid import UUID
from fastapi import HTTPException, status
from supabase import Client

from app.schemas.notification_settings import (
    UserNotificationSettingsCreate,
    UserNotificationSettingsUpdate,
    UserNotificationSettingsResponse,
    validate_email_change_allowed
)
from app.db.supabase import get_supabase_admin


class NotificationSettingsService:
    def __init__(self):
        self.supabase: Client = get_supabase_admin()

    async def get_user_settings(self, user_id: str, user_email: str) -> UserNotificationSettingsResponse:
        """Get user notification settings, create if doesn't exist"""
        try:
            # Try to get existing settings
            response = self.supabase.table("user_notification_settings").select("*").eq("user_id", user_id).execute()
            
            if response.data:
                return UserNotificationSettingsResponse(**response.data[0])
            
            # Create default settings if none exist
            return await self._create_default_settings(user_id, user_email)
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch notification settings: {str(e)}"
            )

    async def update_user_settings(
        self, 
        user_id: str, 
        user_email: str, 
        update_data: UserNotificationSettingsUpdate
    ) -> UserNotificationSettingsResponse:
        """Update user notification settings with validation"""
        try:
            # Get existing settings
            current_settings = await self.get_user_settings(user_id, user_email)
            
            # Validate email change if attempting to update email
            if update_data.notification_email:
                if not validate_email_change_allowed(
                    current_settings.email_address_changed, 
                    update_data.notification_email
                ):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Email address can only be changed once"
                    )
            
            # Prepare update data
            update_dict = {}
            email_changed = False
            
            if update_data.email_notifications_enabled is not None:
                update_dict["email_notifications_enabled"] = update_data.email_notifications_enabled
            
            if update_data.failure_threshold is not None:
                update_dict["failure_threshold"] = update_data.failure_threshold
            
            if update_data.notification_email is not None:
                # Check if email is actually changing
                if update_data.notification_email != current_settings.notification_email:
                    update_dict["notification_email"] = update_data.notification_email
                    update_dict["email_address_changed"] = True
                    email_changed = True
            
            if not update_dict:
                # No changes, return current settings
                return current_settings
            
            # Add updated timestamp
            update_dict["updated_at"] = "NOW()"
            
            # Update in database
            response = self.supabase.table("user_notification_settings").update(update_dict).eq("user_id", user_id).execute()
            
            if not response.data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Settings not found"
                )
            
            return UserNotificationSettingsResponse(**response.data[0])
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update notification settings: {str(e)}"
            )

    async def _create_default_settings(self, user_id: str, user_email: str) -> UserNotificationSettingsResponse:
        """Create default notification settings for new user"""
        try:
            create_data = UserNotificationSettingsCreate(
                user_id=UUID(user_id),
                notification_email=user_email,
                email_notifications_enabled=False,
                failure_threshold=5,
                email_address_changed=False
            )

            data_dict = create_data.dict()

            data_dict['user_id'] = str(data_dict['user_id'])
            
            response = self.supabase.table("user_notification_settings").insert(data_dict).execute()
            
            if not response.data:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create default settings"
                )
            
            return UserNotificationSettingsResponse(**response.data[0])
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create default settings: {str(e)}"
            )