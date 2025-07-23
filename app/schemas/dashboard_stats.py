# app/schemas/dashboard_stats.py

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class UptimeTrendPoint(BaseModel):
    """Single point in uptime trend analysis (daily)"""
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    uptime: float = Field(..., description="Uptime percentage for the day")
    totalChecks: int = Field(..., description="Total checks performed that day")
    successfulChecks: int = Field(..., description="Successful checks that day")


class ResponseTimePoint(BaseModel):
    """Single point in response time trend (hourly)"""
    timestamp: str = Field(..., description="Hour timestamp in ISO format")
    avgResponseTime: int = Field(..., description="Average response time in milliseconds")
    minResponseTime: int = Field(..., description="Minimum response time in milliseconds")
    maxResponseTime: int = Field(..., description="Maximum response time in milliseconds")
    sampleCount: int = Field(..., description="Number of successful checks in this hour")


class IncidentSummary(BaseModel):
    """Summary of a monitoring incident"""
    endpointId: str = Field(..., description="Endpoint ID")
    endpointName: str = Field(..., description="Endpoint display name")
    workspaceName: str = Field(..., description="Workspace name")
    status: str = Field(..., description="Incident status: 'ongoing' or 'resolved'")
    cause: str = Field(..., description="Primary error message")
    durationSeconds: int = Field(..., description="Duration of incident in seconds")
    responseCode: int = Field(..., description="HTTP response code (or 0 if network error)")
    startTime: str = Field(..., description="Incident start time in ISO format")
    endTime: Optional[str] = Field(None, description="Incident end time (null if ongoing)")
    failureCount: int = Field(..., description="Number of consecutive failures")


class EndpointPerformance(BaseModel):
    """Endpoint performance metrics for ranking"""
    endpointId: str = Field(..., description="Endpoint ID")
    endpointName: str = Field(..., description="Endpoint display name")
    workspaceName: str = Field(..., description="Workspace name")
    uptime: float = Field(..., description="Uptime percentage in last 24h")
    avgResponseTime: Optional[int] = Field(None, description="Average response time in ms")
    totalChecks: int = Field(..., description="Total checks in last 24h")
    performanceScore: float = Field(..., description="Calculated performance score for ranking")


class PerformanceStats(BaseModel):
    """Best and worst performing endpoints"""
    bestPerforming: List[EndpointPerformance] = Field(default_factory=list)
    worstPerforming: List[EndpointPerformance] = Field(default_factory=list)


class DashboardStatsResponse(BaseModel):
    """Complete dashboard statistics response"""
    uptimeTrend: List[UptimeTrendPoint] = Field(
        default_factory=list,
        description="7-day uptime trend (available after 7 days of monitoring)"
    )
    responseTimeTrend: List[ResponseTimePoint] = Field(
        default_factory=list,
        description="24-hour hourly response time trend"
    )
    recentIncidents: List[IncidentSummary] = Field(
        default_factory=list,
        description="Recent incidents (3+ consecutive failures)"
    )
    endpointPerformance: PerformanceStats = Field(
        ...,
        description="Best and worst performing endpoints in last 24h"
    )
    generatedAt: datetime = Field(..., description="When this report was generated")
    dataAvailable: bool = Field(..., description="Whether any monitoring data exists")