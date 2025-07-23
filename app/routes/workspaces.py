from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPAuthorizationCredentials
from typing import List
from uuid import UUID
import warnings

from app.schemas.workspace import WorkspaceCreate, WorkspaceUpdate, WorkspaceResponse
from app.schemas.workspace_stats import WorkspaceStatsResponse
from app.services.workspace_service import WorkspaceService
from app.services.workspace_stats_service import WorkspaceStatsService
from app.services.endpoint_service import EndpointService
from app.db.supabase import get_supabase 
from app.core.auth import get_user_id, security
from app.core.rate_limiting import apply_rate_limit

# FIXED: Proper dependency injection for services
def get_workspace_service(supabase = Depends(get_supabase)) -> WorkspaceService:
    return WorkspaceService(supabase)

def get_workspace_stats_service() -> WorkspaceStatsService:
    return WorkspaceStatsService()

def get_endpoint_service(supabase = Depends(get_supabase)) -> EndpointService:
    return EndpointService(supabase)

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
    request: Request,
    workspace_data: WorkspaceCreate,
    user_id: str = Depends(get_user_id),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    workspace_service: WorkspaceService = Depends(get_workspace_service)
):
    """Create a new workspace"""
    await apply_rate_limit(request, "create_workspace", credentials)
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

@router.get("/{workspace_id}/stats", response_model=WorkspaceStatsResponse)
async def get_workspace_stats(
    request: Request,
    workspace_id: UUID,
    user_id: str = Depends(get_user_id),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    stats_service: WorkspaceStatsService = Depends(get_workspace_stats_service)
):
    """Get comprehensive workspace statistics"""
    await apply_rate_limit(request, "workspace_stats", credentials)
    return await stats_service.get_workspace_stats(workspace_id, user_id)

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

# Keep existing deprecated endpoints unchanged for now
@router.get("/{workspace_id}/monitoring")
async def get_workspace_monitoring_stats(
    workspace_id: UUID,
    user_id: str = Depends(get_user_id),
    endpoint_service: EndpointService = Depends(get_endpoint_service),
    supabase = Depends(get_supabase)
):
    """DEPRECATED endpoint"""
    warnings.warn("Deprecated endpoint", DeprecationWarning)
    
    try:
        endpoints = await endpoint_service.get_workspace_endpoints(workspace_id, user_id)
        endpoint_ids = [str(e.id) for e in endpoints]
        
        if not endpoint_ids:
            return []
        
        stats_response = supabase.table("endpoint_stats").select("*").in_("id", endpoint_ids).execute()
        
        for stat in stats_response.data:
            if stat.get('avg_response_time_24h'):
                try:
                    stat['avg_response_time_24h'] = float(stat['avg_response_time_24h'])
                except (ValueError, TypeError):
                    stat['avg_response_time_24h'] = None
            
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
    """DEPRECATED endpoint"""
    warnings.warn("Deprecated endpoint", DeprecationWarning)
    
    workspace = await workspace_service.get_workspace(workspace_id, user_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found"
        )
    
    return await workspace_service.get_workspace_stats(workspace_id, user_id)
