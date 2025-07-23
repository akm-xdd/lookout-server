# app/routes/user_stats.py
from fastapi import APIRouter, Depends
from app.core.auth import get_user_id
from app.services.workspace_service import WorkspaceService
from app.core.constants import MAX_WORKSPACES_PER_USER, MAX_TOTAL_ENDPOINTS_PER_USER


router = APIRouter(prefix="/user", tags=["user"])


@router.get("/stats")
async def get_user_stats(
    user_id: str = Depends(get_user_id),
    workspace_service: WorkspaceService = Depends()
):
    """Get user statistics and limits"""
    
    # Get workspace count
    workspaces = await workspace_service.get_user_workspaces(user_id)
    workspace_count = len(workspaces)
    
    # Calculate total endpoints across all workspaces
    total_endpoints = 0
    for workspace in workspaces:
        stats = await workspace_service.get_workspace_stats(workspace.id, user_id)
        total_endpoints += stats["endpoint_count"]
    
    return {
        "user_id": user_id,
        "limits": {
            "max_workspaces": MAX_WORKSPACES_PER_USER,
            "max_total_endpoints": MAX_TOTAL_ENDPOINTS_PER_USER
        },
        "current": {
            "workspace_count": workspace_count,
            "total_endpoints": total_endpoints
        },
        "remaining": {
            "workspaces": MAX_WORKSPACES_PER_USER - workspace_count,
            "endpoints": MAX_TOTAL_ENDPOINTS_PER_USER - total_endpoints
        },
        "can_create": {
            "workspace": workspace_count < MAX_WORKSPACES_PER_USER,
            "endpoint": total_endpoints < MAX_TOTAL_ENDPOINTS_PER_USER
        }
    }