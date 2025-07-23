from app.services.dashboard_stats_service import DashboardStatsService
from app.services.dashboard_service import DashboardService

def get_dashboard_stats_service() -> DashboardStatsService:
    """Dependency injection for dashboard stats service."""
    return DashboardStatsService()

def get_dashboard_service() -> DashboardService:
    return DashboardService()