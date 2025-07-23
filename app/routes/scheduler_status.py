# app/routes/scheduler_status.py
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPAuthorizationCredentials
from typing import Dict, Any

from app.core.auth import get_user_id, security
from app.core.rate_limiting import apply_rate_limit
from app.services.scheduler_manager import get_scheduler, scheduler_manager
from app.core.config import settings


router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.get("/status")
async def get_scheduler_status(
    user_id: str = Depends(get_user_id)
) -> Dict[str, Any]:
    """
    Get current scheduler status and statistics.
    Requires authentication to prevent information disclosure.
    """
    if not settings.scheduler_enabled:
        return {
            "enabled": False,
            "message": "Scheduler is disabled in configuration"
        }
    
    scheduler = get_scheduler()
    if not scheduler:
        return {
            "enabled": True,
            "status": "not_initialized",
            "message": "Scheduler is not yet initialized"
        }
    
    try:
        status_data = scheduler.get_status()
        return {
            "enabled": True,
            "status": "running" if status_data["is_running"] else "stopped",
            "details": status_data
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get scheduler status: {str(e)}"
        )


@router.post("/health-check")
async def force_health_check(
    request: Request,
    user_id: str = Depends(get_user_id),
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Force an immediate health check.
    Useful for testing or debugging.
    """
    await apply_rate_limit(request, "scheduler_health_check", credentials)
    
    if not settings.scheduler_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduler is disabled"
        )
    
    scheduler = get_scheduler()
    if not scheduler or not scheduler.health_monitor:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler or health monitor not available"
        )
    
    try:
        is_healthy = await scheduler.health_monitor.force_health_check()
        health_status = scheduler.health_monitor.get_health_status()
        
        return {
            "health_check_completed": True,
            "is_healthy": is_healthy,
            "details": health_status
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to perform health check: {str(e)}"
        )


@router.get("/metrics")
async def get_scheduler_metrics(
    user_id: str = Depends(get_user_id)
) -> Dict[str, Any]:
    """
    Get basic scheduler metrics for monitoring.
    Returns lightweight metrics suitable for dashboards.
    """
    if not settings.scheduler_enabled:
        return {
            "enabled": False,
            "endpoints_monitored": 0,
            "queue_size": 0,
            "is_healthy": None
        }
    
    scheduler = get_scheduler()
    if not scheduler:
        return {
            "enabled": True,
            "endpoints_monitored": 0,
            "queue_size": 0,
            "is_healthy": None,
            "status": "not_initialized"
        }
    
    try:
        status_data = scheduler.get_status()
        health_data = status_data.get("health_monitor", {})
        
        return {
            "enabled": True,
            "endpoints_monitored": status_data["endpoint_count"],
            "queue_size": status_data["queue_size"],
            "worker_count": status_data["worker_count"],
            "is_healthy": health_data.get("is_healthy", None),
            "is_running": status_data["is_running"],
            "last_health_check": health_data.get("last_health_check", None)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get scheduler metrics: {str(e)}"
        )