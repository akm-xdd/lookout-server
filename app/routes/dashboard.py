# app/routes/dashboard.py
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from app.core.auth import get_user_id, get_user_email, security
from app.core.rate_limiting import apply_rate_limit
from app.services.dashboard_service import DashboardService
from app.schemas.dashboard import DashboardResponse


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
@router.get("/", response_model=DashboardResponse)
async def get_dashboard_stats(
    request: Request,
    user_id: str = Depends(get_user_id),
    user_email: str = Depends(get_user_email),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    dashboard_service: DashboardService = Depends()
):
    """
    Get complete dashboard statistics in a single API call.
    
    Returns ALL data needed for dashboard charts and metrics:
    - User stats and limits
    - All workspaces with endpoints
    - 7-day uptime trend analysis (available after 7 days)
    - 24-hour hourly average response time
    - Recent incidents list
    - Best and worst performing endpoints (past 24 hours)
    
    This replaces multiple separate endpoints with one comprehensive call
    that eliminates N+1 query problems and reduces API round trips.
    """
    await apply_rate_limit(request, "dashboard", credentials)
    return await dashboard_service.get_dashboard_data(user_id, user_email)