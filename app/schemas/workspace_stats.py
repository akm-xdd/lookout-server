from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID


class WorkspaceStatsEndpoint(BaseModel):
    """Endpoint with comprehensive 24h monitoring statistics."""
    
    # Basic endpoint info
    id: str = Field(..., description="Endpoint UUID")
    name: str = Field(..., description="Endpoint display name")
    url: str = Field(..., description="Target URL")
    method: str = Field(default="GET", description="HTTP method")
    is_active: bool = Field(default=True, description="Whether monitoring is enabled")
    frequency_minutes: int = Field(default=5, description="Check frequency in minutes")
    timeout_seconds: int = Field(default=30, description="Request timeout")
    expected_status: int = Field(default=200, description="Expected HTTP status code")
    created_at: datetime = Field(..., description="Endpoint creation timestamp")
    
    # 24-hour monitoring statistics
    status: str = Field(..., description="Current status: online, warning, offline, unknown, inactive")
    uptime_24h: Optional[float] = Field(None, description="24h uptime percentage")
    avg_response_time_24h: Optional[float] = Field(None, description="24h average response time in ms")
    checks_last_24h: int = Field(default=0, description="Total checks in last 24 hours")
    successful_checks_24h: int = Field(default=0, description="Successful checks in last 24 hours")
    consecutive_failures: int = Field(default=0, description="Current consecutive failure count")
    
    # Latest check information
    last_check_at: Optional[datetime] = Field(None, description="Timestamp of last check")
    last_check_success: Optional[bool] = Field(None, description="Success status of last check")
    last_response_time: Optional[int] = Field(None, description="Response time of last check in ms")
    last_status_code: Optional[int] = Field(None, description="HTTP status code of last check")
    last_error_message: Optional[str] = Field(None, description="Error message from last failed check")

    class Config:
        from_attributes = True


class WorkspaceStatsOverview(BaseModel):
    """Workspace-level overview statistics calculated from active endpoints only."""
    
    # Endpoint counts
    total_endpoints: int = Field(..., description="Total endpoints (including inactive)")
    active_endpoints: int = Field(..., description="Number of active endpoints")
    online_endpoints: int = Field(..., description="Number of online active endpoints")
    warning_endpoints: int = Field(..., description="Number of warning active endpoints")
    offline_endpoints: int = Field(..., description="Number of offline active endpoints")
    unknown_endpoints: int = Field(..., description="Number of unknown status active endpoints")
    
    # Aggregate metrics (24h, active endpoints only)
    avg_uptime_24h: Optional[float] = Field(None, description="Average uptime across active endpoints")
    avg_response_time_24h: Optional[float] = Field(None, description="Average response time across active endpoints")
    total_checks_24h: int = Field(default=0, description="Total checks across all active endpoints")
    successful_checks_24h: int = Field(default=0, description="Successful checks across all active endpoints")
    
    # Timing info
    last_check_at: Optional[datetime] = Field(None, description="Most recent check across all endpoints")


class WorkspaceStatsHealth(BaseModel):
    """Workspace health and incident information."""
    
    status: str = Field(..., description="Overall workspace status: operational, warning, degraded, critical, unknown")
    health_score: Optional[float] = Field(None, description="Health score 0-100 based on online percentage")
    active_incidents: int = Field(default=0, description="Number of ongoing incidents (3+ consecutive failures)")
    last_incident_at: Optional[datetime] = Field(None, description="Timestamp of most recent incident")
    
    # NEW: Performance Weather
    weather: str = Field(..., description="Weather representation: sunny, partly_cloudy, cloudy, stormy, unknown")
    weather_emoji: str = Field(..., description="Weather emoji: ☀️, ⛅, ☁️, ⛈️, ❓")
    weather_description: str = Field(..., description="Human readable weather description")
    
    # Trend data (placeholders for future implementation)
    uptime_trend_7d: List[Dict[str, Any]] = Field(default_factory=list, description="7-day uptime trend")
    response_time_trend_24h: List[Dict[str, Any]] = Field(default_factory=list, description="24h response time trend")


class WorkspaceStatsWorkspace(BaseModel):
    """Basic workspace information."""
    
    id: UUID = Field(..., description="Workspace UUID")
    name: str = Field(..., description="Workspace name")
    description: Optional[str] = Field(None, description="Workspace description")
    user_id: UUID = Field(..., description="Owner user ID")
    created_at: datetime = Field(..., description="Workspace creation timestamp")
    updated_at: datetime = Field(..., description="Last workspace update timestamp")

    class Config:
        from_attributes = True


class WorkspaceStatsIncident(BaseModel):
    """Recent incident information."""
    
    endpoint_id: str = Field(..., description="Endpoint ID that had the incident")
    endpoint_name: str = Field(..., description="Endpoint display name")
    status: str = Field(..., description="Incident status: 'ongoing' or 'resolved'")
    cause: str = Field(..., description="Primary error message")
    duration_minutes: int = Field(..., description="Duration of incident in minutes")
    failure_count: int = Field(..., description="Number of consecutive failures")
    status_code: int = Field(..., description="HTTP status code (0 for network errors)")
    start_time: datetime = Field(..., description="When the incident started")
    end_time: Optional[datetime] = Field(None, description="When the incident ended (null if ongoing)")
    detected_at: datetime = Field(..., description="When the incident was first detected")

    class Config:
        from_attributes = True


class WorkspaceStatsResponse(BaseModel):
    """
    Comprehensive workspace statistics response.
    
    Single endpoint response that provides ALL data needed for workspace page:
    - Basic workspace info
    - All endpoints with 24h monitoring data
    - Calculated workspace-level metrics
    - Health summary and incident tracking
    - Recent incidents (ongoing and resolved)
    
    This replaces multiple API calls and ensures data consistency.
    """
    
    workspace: WorkspaceStatsWorkspace = Field(..., description="Basic workspace information")
    endpoints: List[WorkspaceStatsEndpoint] = Field(..., description="All endpoints with monitoring data")
    overview: WorkspaceStatsOverview = Field(..., description="Workspace-level aggregated metrics")
    health: WorkspaceStatsHealth = Field(..., description="Health status and incident information")
    recent_incidents: List[WorkspaceStatsIncident] = Field(default_factory=list, description="Recent incidents (last 24h)")
    
    # Metadata
    generated_at: datetime = Field(..., description="When this response was generated")
    data_window_hours: int = Field(default=24, description="Data window for statistics (hours)")
    
    class Config:
        from_attributes = True


# Additional helper schemas for specific use cases

class WorkspaceStatsQuickSummary(BaseModel):
    """Quick summary for dashboard cards - subset of full response."""
    
    workspace_id: UUID
    name: str
    status: str
    endpoint_count: int
    active_endpoints: int
    avg_uptime_24h: Optional[float]
    avg_response_time_24h: Optional[float]
    active_incidents: int
    last_check_at: Optional[datetime]

    @classmethod
    def from_full_response(cls, response: WorkspaceStatsResponse) -> 'WorkspaceStatsQuickSummary':
        """Create quick summary from full workspace stats response."""
        return cls(
            workspace_id=response.workspace.id,
            name=response.workspace.name,
            status=response.health.status,
            endpoint_count=response.overview.total_endpoints,
            active_endpoints=response.overview.active_endpoints,
            avg_uptime_24h=response.overview.avg_uptime_24h,
            avg_response_time_24h=response.overview.avg_response_time_24h,
            active_incidents=response.health.active_incidents,
            last_check_at=response.overview.last_check_at
        )
