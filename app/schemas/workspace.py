# app/schemas/workspace.py
from pydantic import BaseModel, Field, validator
from datetime import datetime
from typing import Optional
from uuid import UUID
import re


class WorkspaceBase(BaseModel):
    name: str = Field(
        ..., 
        min_length=1, 
        max_length=100,
        description="Workspace name (1-100 characters)"
    )
    description: Optional[str] = Field(
        None, 
        max_length=500,
        description="Optional workspace description (max 500 characters)"
    )


class WorkspaceCreate(WorkspaceBase):
    """Schema for creating a new workspace"""
    
    @validator('name')
    def validate_name(cls, v):
        # Remove extra whitespace
        v = v.strip()
        
        # Check for empty after strip
        if not v:
            raise ValueError('Workspace name cannot be empty')
        
        # Basic character validation (alphanumeric, spaces, hyphens, underscores)
        if not re.match(r'^[a-zA-Z0-9\s\-_\.]+$', v):
            raise ValueError('Workspace name can only contain letters, numbers, spaces, hyphens, underscores, and periods')
        
        return v
    
    @validator('description')
    def validate_description(cls, v):
        if v is not None:
            v = v.strip()
            # Return None if empty string after strip
            return v if v else None
        return v


class WorkspaceUpdate(BaseModel):
    """Schema for updating a workspace"""
    name: Optional[str] = Field(
        None, 
        min_length=1, 
        max_length=100,
        description="Updated workspace name"
    )
    description: Optional[str] = Field(
        None, 
        max_length=500,
        description="Updated workspace description"
    )
    
    @validator('name')
    def validate_name(cls, v):
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError('Workspace name cannot be empty')
            if not re.match(r'^[a-zA-Z0-9\s\-_\.]+$', v):
                raise ValueError('Workspace name contains invalid characters')
        return v
    
    @validator('description')
    def validate_description(cls, v):
        if v is not None:
            v = v.strip()
            return v if v else None
        return v


class WorkspaceResponse(WorkspaceBase):
    """Schema for workspace API responses"""
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class WorkspaceWithStats(WorkspaceResponse):
    """Extended workspace response with statistics"""
    endpoint_count: int = Field(default=0, description="Number of endpoints in this workspace")
    active_endpoints: int = Field(default=0, description="Number of active endpoints")
    avg_uptime: Optional[float] = Field(None, description="Average uptime percentage")
    last_check: Optional[datetime] = Field(None, description="Last monitoring check time")
    
    class Config:
        from_attributes = True