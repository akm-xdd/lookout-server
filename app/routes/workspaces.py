from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from uuid import UUID
import warnings

from app.schemas.workspace import WorkspaceCreate, WorkspaceUpdate, WorkspaceResponse
from app.schemas.workspace_stats import WorkspaceStatsResponse
from app.services.workspace_service import WorkspaceService
from app.services.workspace_stats_service import WorkspaceStatsService
from app.services.endpoint_service import EndpointService
from app.db.supabase import get_supabase 
from app.core.auth import get_user_id


# Dependency functions
def get_workspace_service() -> WorkspaceService:
    return WorkspaceService()

def get_workspace_stats_service() -> WorkspaceStatsService:
    return WorkspaceStatsService()

def get_endpoint_service() -> EndpointService:
    return EndpointService()


router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("/", response_model=List[WorkspaceResponse])
async def get_workspaces(
    user_id: str = Depends(get_user_id),
    workspace_service: WorkspaceService = Depends(get_workspace_service)
):
    """Get all workspaces for the authenticated user"""
    return await workspace_service.get_user_workspaces(user_id)


@router.post("/", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    workspace_data: WorkspaceCreate,
    user_id: str = Depends(get_user_id),
    workspace_service: WorkspaceService = Depends(get_workspace_service)
):
    """Create a new workspace"""
    return await workspace_service.create_workspace(workspace_data, user_id)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: UUID,
    user_id: str = Depends(get_user_id),
    workspace_service: WorkspaceService = Depends(get_workspace_service)
):
    """Get a specific workspace"""
    workspace = await workspace_service.get_workspace(workspace_id, user_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found"
        )
    return workspace


# NEW: Unified workspace statistics endpoint
@router.get("/{workspace_id}/stats", response_model=WorkspaceStatsResponse)
async def get_workspace_stats(
    workspace_id: UUID,
    user_id: str = Depends(get_user_id),
    stats_service: WorkspaceStatsService = Depends(get_workspace_stats_service)
):
    """
    Get comprehensive workspace statistics in a single API call.
    
    **This is the new unified endpoint that replaces multiple separate calls.**
    
    Returns ALL data needed for the workspace page:
    
    - **Workspace Info**: Basic workspace details
    - **All Endpoints**: Complete endpoint list with 24h monitoring data
    - **Overview Metrics**: Aggregated stats (active endpoints only)
      - Average uptime and response time (24h window)
      - Endpoint status counts (online/warning/offline/unknown)
      - Total checks and success rates
    - **Health Summary**: Overall workspace health and incidents
      - Health score (0-100% based on online endpoints)
      - Active incident count (3+ consecutive failures)
      - Overall status determination
    
    **Key Features:**
    - Only active endpoints contribute to averages and health scores
    - Strict 24-hour data window for all metrics
    - Single database transaction for data consistency
    - Handles inactive/unreachable endpoints correctly
    
    **Performance**: Single optimized query replaces 3+ separate API calls
    """
    return await stats_service.get_workspace_stats(workspace_id, user_id)


@router.get("/{workspace_id}/monitoring")
async def get_workspace_monitoring_stats(
    workspace_id: UUID,
    user_id: str = Depends(get_user_id),
    endpoint_service: EndpointService = Depends(get_endpoint_service),
    supabase = Depends(get_supabase)
):
    """
    Get real-time monitoring stats for all endpoints in a workspace.
    
    **DEPRECATED**: Use GET /workspaces/{workspace_id}/stats instead.
    This endpoint will be removed in a future version.
    """
    warnings.warn(
        "GET /workspaces/{workspace_id}/monitoring is deprecated. "
        "Use GET /workspaces/{workspace_id}/stats instead.",
        DeprecationWarning,
        stacklevel=2
    )
    
    try:
        # Get endpoint IDs for this workspace
        endpoints = await endpoint_service.get_workspace_endpoints(workspace_id, user_id)
        endpoint_ids = [str(e.id) for e in endpoints]
        
        if not endpoint_ids:
            return []
        
        # Get monitoring stats from the view
        stats_response = supabase.table("endpoint_stats").select("*").in_("id", endpoint_ids).execute()
        
        # Convert string numbers to actual numbers
        for stat in stats_response.data:
            # Convert avg_response_time_24h from string to float
            if stat.get('avg_response_time_24h'):
                try:
                    stat['avg_response_time_24h'] = float(stat['avg_response_time_24h'])
                except (ValueError, TypeError):
                    stat['avg_response_time_24h'] = None
            
            # Ensure other numeric fields are proper types
            stat['checks_last_24h'] = stat.get('checks_last_24h') or 0
            stat['successful_checks_24h'] = stat.get('successful_checks_24h') or 0
            stat['consecutive_failures'] = stat.get('consecutive_failures') or 0
            stat['last_response_time'] = stat.get('last_response_time') or None
            stat['last_status_code'] = stat.get('last_status_code') or None
        
        return stats_response.data
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get workspace monitoring stats: {str(e)}"
        )


@router.get("/{workspace_id}/legacy-stats")
async def get_workspace_legacy_stats(
    workspace_id: UUID,
    user_id: str = Depends(get_user_id),
    workspace_service: WorkspaceService = Depends(get_workspace_service)
):
    """
    Get workspace statistics (endpoint counts, limits, etc.)
    
    **DEPRECATED**: Use GET /workspaces/{workspace_id}/stats instead.
    This endpoint will be removed in a future version.
    """
    warnings.warn(
        "GET /workspaces/{workspace_id}/legacy-stats is deprecated. "
        "Use GET /workspaces/{workspace_id}/stats instead.",
        DeprecationWarning,
        stacklevel=2
    )
    
    # Validate workspace exists and belongs to user
    workspace = await workspace_service.get_workspace(workspace_id, user_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found"
        )
    
    return await workspace_service.get_workspace_stats(workspace_id, user_id)


@router.put("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: UUID,
    workspace_data: WorkspaceUpdate,
    user_id: str = Depends(get_user_id),
    workspace_service: WorkspaceService = Depends(get_workspace_service)
):
    """Update a workspace"""
    workspace = await workspace_service.update_workspace(workspace_id, workspace_data, user_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found"
        )
    return workspace


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: UUID,
    user_id: str = Depends(get_user_id),
    workspace_service: WorkspaceService = Depends(get_workspace_service)
):
    """Delete a workspace"""
    deleted = await workspace_service.delete_workspace(workspace_id, user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found"
        )
