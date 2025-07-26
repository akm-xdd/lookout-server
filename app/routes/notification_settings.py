# app/routes/notification_settings.py
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials

from app.schemas.notification_settings import (
    UserNotificationSettingsResponse,
    UserNotificationSettingsUpdate
)
from app.services.notification_settings_service import NotificationSettingsService
from app.core.auth import get_user_id, get_user_email, security
from app.core.rate_limiting import apply_rate_limit


router = APIRouter(prefix="/user/notification-settings", tags=["notifications"])


@router.get("/", response_model=UserNotificationSettingsResponse)
async def get_notification_settings(
    user_id: str = Depends(get_user_id),
    user_email: str = Depends(get_user_email),
    settings_service: NotificationSettingsService = Depends()
):
    """Get user notification settings, creates default if not exists"""
    return await settings_service.get_user_settings(user_id, user_email)


@router.put("/", response_model=UserNotificationSettingsResponse)
async def update_notification_settings(
    request: Request,
    update_data: UserNotificationSettingsUpdate,
    user_id: str = Depends(get_user_id),
    user_email: str = Depends(get_user_email),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    settings_service: NotificationSettingsService = Depends()
):
    """Update user notification settings"""
    await apply_rate_limit(request, "update_notification_settings", credentials)
    return await settings_service.update_user_settings(user_id, user_email, update_data)