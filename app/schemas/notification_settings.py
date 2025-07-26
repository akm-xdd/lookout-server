# app/schemas/notification_settings.py
from pydantic import BaseModel, Field, EmailStr, validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class UserNotificationSettingsBase(BaseModel):
    """Base schema for user notification settings"""
    email_notifications_enabled: bool = Field(
        default=False,
        description="Whether email notifications are enabled"
    )
    notification_email: EmailStr = Field(
        ...,
        description="Email address for notifications (separate from account email)"
    )
    failure_threshold: int = Field(
        default=5,
        ge=5,
        le=20,
        description="Number of consecutive failures before sending notification"
    )


class UserNotificationSettingsCreate(UserNotificationSettingsBase):
    """Schema for creating notification settings (auto-populated on user signup)"""
    user_id: UUID = Field(..., description="User ID from auth.users")

    # These are set by the system, not user input
    email_address_changed: bool = Field(
        default=False, description="Tracks if user used their one email change")


class UserNotificationSettingsUpdate(BaseModel):
    """Schema for updating notification settings via API"""
    email_notifications_enabled: Optional[bool] = Field(
        None,
        description="Enable/disable email notifications"
    )
    notification_email: Optional[EmailStr] = Field(
        None,
        description="New notification email (can only be changed once)"
    )
    failure_threshold: Optional[int] = Field(
        None,
        ge=5,
        le=20,
        description="Consecutive failures threshold (5-20)"
    )

    @validator('notification_email')
    def validate_notification_email(cls, v):
        if v is not None:
            # Additional validation for problematic email patterns
            email_lower = v.lower()

            # Warn about no-reply addresses (but allow them)
            if 'no-reply' in email_lower or 'noreply' in email_lower:
                # This would be handled in the UI with a warning, not blocking here
                pass

        return v


class UserNotificationSettingsResponse(UserNotificationSettingsBase):
    """Schema for API responses"""
    id: UUID
    user_id: UUID
    email_address_changed: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NotificationHistoryCreate(BaseModel):
    """Schema for recording sent notifications"""
    user_id: UUID
    workspace_id: UUID
    endpoint_ids: List[UUID] = Field(...,
                                     description="Array of failing endpoint IDs")
    failure_counts: List[int] = Field(
        ..., description="Corresponding failure counts for each endpoint")

    @validator('failure_counts')
    def validate_failure_counts_length(cls, v, values):
        if 'endpoint_ids' in values and len(v) != len(values['endpoint_ids']):
            raise ValueError(
                "failure_counts must have same length as endpoint_ids")
        return v


class NotificationHistoryResponse(BaseModel):
    """Schema for notification history responses"""
    id: UUID
    user_id: UUID
    workspace_id: UUID
    endpoint_ids: List[UUID]
    failure_counts: List[int]
    sent_at: datetime

    class Config:
        from_attributes = True


class FailingEndpointInfo(BaseModel):
    """Schema for endpoint failure information in email context"""
    id: UUID
    name: str
    consecutive_failures: int
    last_check_at: Optional[datetime]
    workspace_id: UUID
    workspace_name: str


class WorkspaceNotificationBatch(BaseModel):
    """Schema for batched workspace notifications"""
    user_id: UUID
    workspace_id: UUID
    workspace_name: str
    notification_email: str
    failing_endpoints: List[FailingEndpointInfo]
    failure_threshold: int

    @property
    def total_failing_endpoints(self) -> int:
        return len(self.failing_endpoints)


class EmailNotificationPayload(BaseModel):
    """Schema for email service payload"""
    to_email: str
    workspace_name: str
    failing_endpoints: List[FailingEndpointInfo]
    dashboard_link: str
    cooldown_hours: int = Field(...,
                                description="Hours until next notification possible")


# Validation helpers
def validate_email_change_allowed(email_address_changed: bool, new_email: Optional[str]) -> bool:
    """Check if user is allowed to change their email address"""
    if new_email is not None and email_address_changed:
        return False  # Already used their one change
    return True
