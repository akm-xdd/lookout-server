# app/routes/dashboard_stats.py
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from app.core.auth import get_user_id, security
from app.core.rate_limiting import apply_rate_limit
from app.services.dashboard_stats_service import DashboardStatsService
from app.schemas.dashboard_stats import DashboardStatsResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard-stats"])


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    request: Request,
    user_id: str = Depends(get_user_id),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    stats_service: DashboardStatsService = Depends()
):
    """
    Get comprehensive dashboard statistics in a single API call.
    
    This endpoint replaces multiple separate chart data endpoints and provides:
    
    1. **Uptime Trend Analysis**: 7-day daily uptime percentages across all endpoints
       - Only available after 7 days of monitoring data
       - Shows overall health trends
    
    2. **Response Time Trend**: Past 24 hours hourly average response times
       - Hourly aggregation for performance monitoring
       - Includes min/max/sample count for each hour
    
    3. **Recent Incidents**: Last 10 incidents (3+ consecutive failures)
       - Shows ongoing and resolved incidents
       - Includes duration, cause, and affected endpoints
    
    4. **Endpoint Performance**: Best and worst performing endpoints (24h)
       - Ranked by performance score (uptime weighted, response time penalized)
       - Minimum 3 checks required to qualify
    
    **Performance**: Single database query optimized for minimal egress usage.
    **Caching**: Response can be cached for 5-10 minutes on frontend.
    """
    await apply_rate_limit(request, "dashboard", credentials)
    return await stats_service.get_dashboard_stats(user_id)


@router.get("/stats/availability")
async def get_stats_availability(
    user_id: str = Depends(get_user_id),
    stats_service: DashboardStatsService = Depends()
):
    """
    Quick check to determine if dashboard charts should be displayed.
    Returns basic info about data availability without full computation.
    """
    try:
        endpoint_ids = await stats_service._get_user_endpoint_ids(user_id)
        
        if not endpoint_ids:
            return {
                "hasEndpoints": False,
                "hasRecentData": False,
                "hasHistoricalData": False,
                "endpointCount": 0
            }
        
        from datetime import datetime, timedelta
        twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).isoformat()
        
        recent_checks = stats_service.supabase.table("check_results").select(
            "id", count="exact"
        ).in_(
            "endpoint_id", endpoint_ids
        ).gte(
            "checked_at", twenty_four_hours_ago
        ).limit(1).execute()
        
        seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
        
        historical_checks = stats_service.supabase.table("check_results").select(
            "id", count="exact"
        ).in_(
            "endpoint_id", endpoint_ids
        ).lte(
            "checked_at", seven_days_ago
        ).limit(1).execute()
        
        return {
            "hasEndpoints": True,
            "hasRecentData": recent_checks.count > 0,
            "hasHistoricalData": historical_checks.count > 0,
            "endpointCount": len(endpoint_ids)
        }
        
    except Exception as e:
        print(f"❌ Stats availability error: {e}")
        return {
            "hasEndpoints": False,
            "hasRecentData": False, 
            "hasHistoricalData": False,
            "endpointCount": 0
        }
