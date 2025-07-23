from pydantic import BaseModel, Field, validator, HttpUrl
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID
import re

from app.core.constants import (
    ALLOWED_HTTP_METHODS,
    MIN_CHECK_FREQUENCY_SECONDS,
    MAX_CHECK_FREQUENCY_SECONDS,
    MIN_TIMEOUT_SECONDS,
    MAX_TIMEOUT_SECONDS,
    MIN_EXPECTED_STATUS_CODE,
    MAX_EXPECTED_STATUS_CODE,
    MAX_ENDPOINT_NAME_LENGTH,
    MAX_HEADERS_COUNT,
    MAX_HEADER_KEY_LENGTH,
    MAX_HEADER_VALUE_LENGTH,
    MAX_BODY_LENGTH
)

# HELPER VALIDATION FUNCTIONS (to avoid duplication)
def validate_endpoint_name(v):
    if v is not None:
        v = v.strip()
        if not v:
            raise ValueError('Endpoint name cannot be empty')
    return v

def validate_endpoint_url(v):
    if v is not None:
        v = v.strip()
        if not v:
            raise ValueError('URL cannot be empty')
        
        # Check if URL has protocol
        if not re.match(r'^https?://', v, re.IGNORECASE):
            raise ValueError('URL must start with http:// or https://')
        
        # Basic URL format validation
        if not re.match(r'^https?://[^\s/$.?#].[^\s]*$', v, re.IGNORECASE):
            raise ValueError('Invalid URL format')
    return v

def validate_endpoint_method(v):
    if v is not None:
        v = v.upper().strip()
        if v not in ALLOWED_HTTP_METHODS:
            raise ValueError(f'HTTP method must be one of: {", ".join(ALLOWED_HTTP_METHODS)}')
    return v

def validate_endpoint_headers(v):
    if not v:
        return {}
    
    if len(v) > MAX_HEADERS_COUNT:
        raise ValueError(f'Maximum {MAX_HEADERS_COUNT} headers allowed')
    
    validated_headers = {}
    for key, value in v.items():
        # Validate header key
        if not key or len(key.strip()) == 0:
            raise ValueError('Header keys cannot be empty')
        
        key = key.strip()
        if len(key) > MAX_HEADER_KEY_LENGTH:
            raise ValueError(f'Header key too long (max {MAX_HEADER_KEY_LENGTH} characters)')
        
        # Basic header key validation (no special characters)
        if not re.match(r'^[a-zA-Z0-9\-_]+$', key):
            raise ValueError(f'Invalid header key: {key}. Only letters, numbers, hyphens, and underscores allowed')
        
        # Validate header value
        if value is None:
            value = ""
        else:
            value = str(value).strip()
        
        if len(value) > MAX_HEADER_VALUE_LENGTH:
            raise ValueError(f'Header value too long (max {MAX_HEADER_VALUE_LENGTH} characters)')
        
        validated_headers[key] = value
    
    return validated_headers

def validate_endpoint_body(v, values):
    if v is not None:
        v = v.strip()
        if not v:
            return None
        
        # Only allow body for methods that support it
        method = values.get('method', '').upper()
        if method in ['GET', 'HEAD', 'DELETE'] and v:
            raise ValueError(f'Request body not allowed for {method} method')
    
    return v


class EndpointBase(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=MAX_ENDPOINT_NAME_LENGTH,
        description="Endpoint name for identification"
    )
    url: str = Field(
        ...,
        description="Full URL to monitor (must include protocol)"
    )
    method: str = Field(
        default="GET",
        description="HTTP method to use"
    )
    headers: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        description="HTTP headers to send with the request"
    )
    body: Optional[str] = Field(
        None,
        max_length=MAX_BODY_LENGTH,
        description="Request body (for POST/PUT requests)"
    )
    expected_status: int = Field(
        default=200,
        ge=MIN_EXPECTED_STATUS_CODE,
        le=MAX_EXPECTED_STATUS_CODE,
        description="Expected HTTP status code"
    )
    frequency_minutes: int = Field(
        default=5,
        ge=5,
        le=60,
        description="Check frequency in minutes"
    )
    timeout_seconds: int = Field(
        default=30,
        ge=MIN_TIMEOUT_SECONDS,
        le=MAX_TIMEOUT_SECONDS,
        description="Request timeout in seconds"
    )
    is_active: bool = Field(
        default=True,
        description="Whether monitoring is enabled for this endpoint"
    )

    @validator('name')
    def validate_name(cls, v):
        return validate_endpoint_name(v)

    @validator('url')
    def validate_url(cls, v):
        return validate_endpoint_url(v)

    @validator('method')
    def validate_method(cls, v):
        return validate_endpoint_method(v)

    @validator('headers')
    def validate_headers(cls, v):
        return validate_endpoint_headers(v)

    @validator('body')
    def validate_body(cls, v, values):
        return validate_endpoint_body(v, values)

    @validator('frequency_minutes')
    def validate_frequency(cls, v):
        # Convert minutes to seconds for validation
        frequency_seconds = v * 60
        if frequency_seconds < MIN_CHECK_FREQUENCY_SECONDS:
            raise ValueError(f'Check frequency too low (minimum {MIN_CHECK_FREQUENCY_SECONDS // 60} minute)')
        if frequency_seconds > MAX_CHECK_FREQUENCY_SECONDS:
            raise ValueError(f'Check frequency too high (maximum {MAX_CHECK_FREQUENCY_SECONDS // 60} minutes)')
        return v


class EndpointCreate(EndpointBase):
    """Schema for creating a new endpoint"""
    pass


class EndpointUpdate(BaseModel):
    """Schema for updating an endpoint"""
    name: Optional[str] = Field(None, min_length=1, max_length=MAX_ENDPOINT_NAME_LENGTH)
    url: Optional[str] = None
    method: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    body: Optional[str] = Field(None, max_length=MAX_BODY_LENGTH)
    expected_status: Optional[int] = Field(None, ge=MIN_EXPECTED_STATUS_CODE, le=MAX_EXPECTED_STATUS_CODE)
    frequency_minutes: Optional[int] = Field(None, ge=1, le=60)
    timeout_seconds: Optional[int] = Field(None, ge=MIN_TIMEOUT_SECONDS, le=MAX_TIMEOUT_SECONDS)
    is_active: Optional[bool] = None

    # Use the helper functions directly instead of referencing base class validators
    @validator('name')
    def validate_name(cls, v):
        return validate_endpoint_name(v)

    @validator('url')
    def validate_url(cls, v):
        return validate_endpoint_url(v)

    @validator('method')
    def validate_method(cls, v):
        return validate_endpoint_method(v)

    @validator('headers')
    def validate_headers(cls, v):
        if v is not None:
            return validate_endpoint_headers(v)
        return v

    @validator('body')
    def validate_body(cls, v, values):
        if v is not None:
            return validate_endpoint_body(v, values)
        return v

    @validator('frequency_minutes')
    def validate_frequency(cls, v):
        if v is not None:
            # Convert minutes to seconds for validation
            frequency_seconds = v * 60
            if frequency_seconds < MIN_CHECK_FREQUENCY_SECONDS:
                raise ValueError(f'Check frequency too low (minimum {MIN_CHECK_FREQUENCY_SECONDS // 60} minute)')
            if frequency_seconds > MAX_CHECK_FREQUENCY_SECONDS:
                raise ValueError(f'Check frequency too high (maximum {MAX_CHECK_FREQUENCY_SECONDS // 60} minutes)')
        return v


class EndpointResponse(EndpointBase):
    """Schema for endpoint API responses"""
    id: UUID
    workspace_id: UUID
    created_at: datetime
    
    class Config:
        from_attributes = True


class EndpointWithStats(EndpointResponse):
    """Extended endpoint response with monitoring statistics"""
    last_check: Optional[datetime] = None
    last_status_code: Optional[int] = None
    last_response_time: Optional[int] = None
    uptime_percentage: Optional[float] = None
    total_checks: int = 0
    successful_checks: int = 0
    
    class Config:
        from_attributes = True