from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from app.schemas.workspace import WorkspaceResponse
from app.schemas.endpoint import EndpointResponse


class DashboardUserLimits(BaseModel):
    """User limits and quotas"""
    max_workspaces: int = Field(..., description="Maximum workspaces allowed")
    max_total_endpoints: int = Field(..., description="Maximum total endpoints allowed")


class DashboardUserCurrent(BaseModel):
    """Current user usage"""
    workspace_count: int = Field(..., description="Current number of workspaces")
    total_endpoints: int = Field(..., description="Current total endpoints")


class DashboardUserStats(BaseModel):
    """User statistics and limits"""
    id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    limits: DashboardUserLimits
    current: DashboardUserCurrent


class DashboardWorkspace(BaseModel):
    """Workspace with embedded endpoints for dashboard"""
    id: UUID
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    user_id: UUID
    endpoint_count: int = Field(..., description="Number of endpoints in workspace")
    endpoints: List[EndpointResponse] = Field(default_factory=list)
    status: str = Field(default='unknown', description="Workspace status: online, warning, offline, unknown")
    uptime: Optional[float] = Field(default=None, description="Workspace average uptime percentage")
    avg_response_time: Optional[float] = Field(default=None, description="Workspace average response time")
    last_check: Optional[str] = Field(default=None, description="Last check timestamp across all endpoints")
    active_incidents: int = Field(default=0, description="Number of active incidents in workspace")


class EndpointPerformance(BaseModel):
    """Endpoint performance metrics"""
    endpointName: str
    workspaceName: str
    avgResponseTime: int  # milliseconds
    uptime: float  # percentage


class DashboardOverview(BaseModel):
    """Dashboard overview statistics with all chart data"""
    total_endpoints: int = Field(..., description="Total endpoints across all workspaces")
    active_endpoints: int = Field(..., description="Number of active endpoints")
    total_workspaces: int = Field(..., description="Total number of workspaces")
    
    # Chart data
    uptimeHistory: List[dict] = Field(default_factory=list, description="7-day uptime trend: [{date, uptime}]")
    responseTimeHistory: List[dict] = Field(default_factory=list, description="24h response time: [{timestamp, avgResponseTime}]")
    
    # Performance data
    bestPerformingEndpoints: List[EndpointPerformance] = Field(default_factory=list, description="Top 3 best performing endpoints")
    worstPerformingEndpoints: List[EndpointPerformance] = Field(default_factory=list, description="Top 3 worst performing endpoints")


class DashboardIncident(BaseModel):
    """Incident information for dashboard"""
    id: str
    endpointName: str
    workspaceName: str
    status: str  # 'ongoing' or 'resolved'
    cause: str
    duration: int  # seconds
    responseCode: int
    startTime: str
    endTime: Optional[str] = None


class DashboardResponse(BaseModel):
    """Complete dashboard data response - ALL data in one call"""
    user: DashboardUserStats
    workspaces: List[DashboardWorkspace]
    overview: DashboardOverview
    recentIncidents: List[DashboardIncident] = Field(default_factory=list)
