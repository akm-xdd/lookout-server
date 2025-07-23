# app/routes/endpoints.py
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPAuthorizationCredentials
from typing import List
from uuid import UUID

from app.schemas.endpoint import EndpointCreate, EndpointUpdate, EndpointResponse
from app.services.endpoint_service import EndpointService
from app.core.auth import get_user_id, security
from app.core.rate_limiting import apply_rate_limit
from app.services.scheduler_manager import (
    notify_endpoint_created,
    notify_endpoint_updated,
    notify_endpoint_deleted
)


router = APIRouter(prefix="/workspaces/{workspace_id}/endpoints", tags=["endpoints"])


@router.get("/", response_model=List[EndpointResponse])
async def get_workspace_endpoints(
    workspace_id: UUID,
    user_id: str = Depends(get_user_id),
    endpoint_service: EndpointService = Depends()
):
    """Get all endpoints for a workspace"""
    return await endpoint_service.get_workspace_endpoints(workspace_id, user_id)


@router.post("/", response_model=EndpointResponse, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    request: Request,
    workspace_id: UUID,
    endpoint_data: EndpointCreate,
    user_id: str = Depends(get_user_id),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    endpoint_service: EndpointService = Depends()
):
    """Create a new endpoint in a workspace"""
    await apply_rate_limit(request, "create_endpoint", credentials)
    
    endpoint = await endpoint_service.create_endpoint(endpoint_data, workspace_id, user_id)
    notify_endpoint_created(endpoint.dict())
    return endpoint


@router.get("/{endpoint_id}", response_model=EndpointResponse)
async def get_endpoint(
    workspace_id: UUID,
    endpoint_id: UUID,
    user_id: str = Depends(get_user_id),
    endpoint_service: EndpointService = Depends()
):
    """Get a specific endpoint"""
    endpoint = await endpoint_service.get_endpoint(endpoint_id, user_id)
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Endpoint not found"
        )
    
    if endpoint.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Endpoint not found in this workspace"
        )
    
    return endpoint


@router.put("/{endpoint_id}", response_model=EndpointResponse)
async def update_endpoint(
    workspace_id: UUID,
    endpoint_id: UUID,
    endpoint_data: EndpointUpdate,
    user_id: str = Depends(get_user_id),
    endpoint_service: EndpointService = Depends()
):
    """Update an endpoint"""
    endpoint = await endpoint_service.update_endpoint(endpoint_id, endpoint_data, user_id)
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Endpoint not found"
        )
    
    if endpoint.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Endpoint not found in this workspace"
        )
    
    notify_endpoint_updated(str(endpoint_id), endpoint.dict())
    return endpoint


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    workspace_id: UUID,
    endpoint_id: UUID,
    user_id: str = Depends(get_user_id),
    endpoint_service: EndpointService = Depends()
):
    """Delete an endpoint"""
    endpoint = await endpoint_service.get_endpoint(endpoint_id, user_id)
    if not endpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Endpoint not found"
        )
    
    if endpoint.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Endpoint not found in this workspace"
        )
    
    deleted = await endpoint_service.delete_endpoint(endpoint_id, user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Endpoint not found"
        )
    notify_endpoint_deleted(str(endpoint_id))
    

@router.post("/{endpoint_id}/test")
async def test_endpoint(
    request: Request,
    workspace_id: UUID,
    endpoint_id: UUID,
    user_id: str = Depends(get_user_id),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    endpoint_service: EndpointService = Depends()
):
    """Test an endpoint manually"""
    await apply_rate_limit(request, "test_endpoint", credentials)
    return await endpoint_service.test_endpoint(endpoint_id, user_id)