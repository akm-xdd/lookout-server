from fastapi import Depends, HTTPException, status
from supabase import Client
from typing import List, Optional
from uuid import UUID

from app.db.supabase import get_supabase
from app.schemas.endpoint import EndpointCreate, EndpointUpdate, EndpointResponse
from app.core.constants import MAX_ENDPOINTS_PER_WORKSPACE, MAX_TOTAL_ENDPOINTS_PER_USER
import json
import hashlib
from app.core.url_validator import validate_monitoring_url


class EndpointService:
    def __init__(self, supabase: Client = Depends(get_supabase)):
        self.supabase = supabase

    async def _validate_workspace_ownership(self, workspace_id: UUID, user_id: str) -> None:
        """Validate that the workspace belongs to the user"""
        try:
            response = self.supabase.table("workspaces").select("id").eq("id", str(workspace_id)).eq("user_id", user_id).execute()
            
            if not response.data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Workspace not found or access denied"
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to validate workspace ownership: {str(e)}"
            )

    async def _get_workspace_endpoint_count(self, workspace_id: UUID) -> int:
        """Get the current number of endpoints in a workspace"""
        try:
            response = self.supabase.table("endpoints").select("id", count="exact").eq("workspace_id", str(workspace_id)).execute()
            return response.count or 0
        except Exception:
            return 0

    async def _get_user_total_endpoint_count(self, user_id: str) -> int:
        """Get the total number of endpoints across all user's workspaces"""
        try:
            # First get all workspace IDs for the user
            workspaces_response = self.supabase.table("workspaces").select("id").eq("user_id", user_id).execute()
            
            if not workspaces_response.data:
                return 0
            
            workspace_ids = [ws["id"] for ws in workspaces_response.data]
            
            # Then count endpoints in those workspaces
            endpoints_response = self.supabase.table("endpoints").select("id", count="exact").in_("workspace_id", workspace_ids).execute()
            return endpoints_response.count or 0
        except Exception as e:
            print(f"Warning: Could not get user total endpoint count: {e}")
            return 0

    async def _validate_endpoint_limits(self, workspace_id: UUID, user_id: str) -> None:
        """Validate endpoint limits for workspace and user"""
        # Check workspace endpoint limit
        workspace_count = await self._get_workspace_endpoint_count(workspace_id)
        if workspace_count >= MAX_ENDPOINTS_PER_WORKSPACE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Maximum {MAX_ENDPOINTS_PER_WORKSPACE} endpoints allowed per workspace. This workspace has {workspace_count}."
            )
        
        # Check user total endpoint limit
        user_total = await self._get_user_total_endpoint_count(user_id)
        if user_total >= MAX_TOTAL_ENDPOINTS_PER_USER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Maximum {MAX_TOTAL_ENDPOINTS_PER_USER} total endpoints allowed per user. You currently have {user_total}."
            )

    async def _validate_endpoint_name_unique(self, name: str, workspace_id: UUID, exclude_id: Optional[UUID] = None) -> None:
        """Validate that endpoint name is unique within the workspace"""
        try:
            query = self.supabase.table("endpoints").select("id").eq("workspace_id", str(workspace_id)).eq("name", name)
            
            if exclude_id:
                query = query.neq("id", str(exclude_id))
            
            response = query.execute()
            
            if response.data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"An endpoint named '{name}' already exists in this workspace. Please choose a different name."
                )
        except HTTPException:
            raise
        except Exception as e:
            print(f"Warning: Could not validate endpoint name uniqueness: {e}")

    async def _validate_endpoint_config_unique(self, url: str, method: str, headers: Optional[dict], body: Optional[str], workspace_id: UUID, exclude_id: Optional[UUID] = None) -> None:
        """Validate that the complete endpoint configuration is unique within the workspace"""
        try:
            # Get all endpoints in the workspace to compare configurations
            query = self.supabase.table("endpoints").select("id, url, method, headers, body").eq("workspace_id", str(workspace_id))
            
            if exclude_id:
                query = query.neq("id", str(exclude_id))
            
            response = query.execute()
            
            # Normalize the new endpoint configuration for comparison
            new_config = {
                "url": url.strip(),
                "method": method.upper().strip(),
                "headers": headers or {},
                "body": (body or "").strip()
            }
            
            # Check against existing endpoints
            for existing_endpoint in response.data:
                existing_config = {
                    "url": existing_endpoint.get("url", "").strip(),
                    "method": existing_endpoint.get("method", "").upper().strip(),
                    "headers": existing_endpoint.get("headers") or {},
                    "body": (existing_endpoint.get("body") or "").strip()
                }
                
                # Compare configurations
                if self._configs_are_identical(new_config, existing_config):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"An identical endpoint configuration already exists in this workspace. Please modify the URL, method, headers, or body to create a unique endpoint."
                    )
            
        except HTTPException:
            raise
        except Exception as e:
            print(f"Warning: Could not validate endpoint configuration uniqueness: {e}")

    def _configs_are_identical(self, config1: dict, config2: dict) -> bool:
        """Compare two endpoint configurations for exact match"""
        # Compare URL and method (case-insensitive for method)
        if config1["url"] != config2["url"]:
            return False
        
        if config1["method"] != config2["method"]:
            return False
        
        # Compare headers (normalize keys to lowercase for comparison)
        headers1 = {k.lower(): str(v).strip() for k, v in (config1["headers"] or {}).items()}
        headers2 = {k.lower(): str(v).strip() for k, v in (config2["headers"] or {}).items()}
        
        if headers1 != headers2:
            return False
        
        # Compare body content (normalized)
        body1 = config1["body"].strip()
        body2 = config2["body"].strip()
        
        if body1 != body2:
            return False
        
        return True

    async def get_workspace_endpoints(self, workspace_id: UUID, user_id: str) -> List[EndpointResponse]:
        """Get all endpoints for a workspace"""
        # Validate workspace ownership
        await self._validate_workspace_ownership(workspace_id, user_id)
        
        try:
            response = self.supabase.table("endpoints").select("*").eq("workspace_id", str(workspace_id)).order("created_at", desc=False).execute()
            return [EndpointResponse(**endpoint) for endpoint in response.data]
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch endpoints: {str(e)}"
            )

    async def create_endpoint(self, endpoint_data: EndpointCreate, workspace_id: UUID, user_id: str) -> EndpointResponse:
        """Create a new endpoint with validation"""
        # Validate workspace ownership
        await self._validate_workspace_ownership(workspace_id, user_id)
        
        # Validate endpoint limits
        await self._validate_endpoint_limits(workspace_id, user_id)

        # Validate URL security
        is_valid, error_message = validate_monitoring_url(endpoint_data.url)

        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid endpoint URL: {error_message}"
            )

        # Validate unique name within workspace
        await self._validate_endpoint_name_unique(endpoint_data.name, workspace_id)
        
        # Validate unique complete configuration within workspace
        await self._validate_endpoint_config_unique(
            url=endpoint_data.url,
            method=endpoint_data.method,
            headers=endpoint_data.headers,
            body=endpoint_data.body,
            workspace_id=workspace_id
        )
        
        
        try:
            data = {
                **endpoint_data.dict(),
                "workspace_id": str(workspace_id)
            }
            
            response = self.supabase.table("endpoints").insert(data).execute()

            if response.data:
                from app.db.redis import cache

                dashboard_pattern = f"dashboard:get_dashboard_data:{user_id}:*"
                await cache.delete_pattern(dashboard_pattern)

                workspace_key = f"workspace_stats:get_workspace_stats:{workspace_id}:{user_id}"
                await cache.delete(workspace_key)
                print(f"✅ Created endpoint and cleared cache: {dashboard_pattern}, {workspace_key}")

            if not response.data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to create endpoint"
                )
            
            return EndpointResponse(**response.data[0])
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create endpoint: {str(e)}"
            )

    async def get_endpoint(self, endpoint_id: UUID, user_id: str) -> Optional[EndpointResponse]:
        """Get a specific endpoint"""
        try:
            # First get the endpoint
            endpoint_response = self.supabase.table("endpoints").select("*").eq("id", str(endpoint_id)).execute()
            
            if not endpoint_response.data:
                return None
            
            endpoint = endpoint_response.data[0]
            
            # Then validate workspace ownership
            await self._validate_workspace_ownership(UUID(endpoint["workspace_id"]), user_id)
            
            return EndpointResponse(**endpoint)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch endpoint: {str(e)}"
            )

    async def update_endpoint(self, endpoint_id: UUID, endpoint_data: EndpointUpdate, user_id: str) -> Optional[EndpointResponse]:
        """Update an endpoint with validation"""
        # Get existing endpoint to validate ownership and get workspace_id
        existing_endpoint = await self.get_endpoint(endpoint_id, user_id)
        if not existing_endpoint:
            return None
        
        # Validate unique name if it's being updated
        if endpoint_data.name:
            await self._validate_endpoint_name_unique(endpoint_data.name, existing_endpoint.workspace_id, endpoint_id)
        
        # Validate unique configuration if any core fields are being updated
        if any([endpoint_data.url, endpoint_data.method, endpoint_data.headers, endpoint_data.body]):
            new_url = endpoint_data.url or existing_endpoint.url
            new_method = endpoint_data.method or existing_endpoint.method
            new_headers = endpoint_data.headers if endpoint_data.headers is not None else existing_endpoint.headers
            new_body = endpoint_data.body if endpoint_data.body is not None else existing_endpoint.body
            
            await self._validate_endpoint_config_unique(
                url=new_url,
                method=new_method,
                headers=new_headers,
                body=new_body,
                workspace_id=existing_endpoint.workspace_id,
                exclude_id=endpoint_id
            )
        
        try:
            # Only include non-None values in update
            update_data = {k: v for k, v in endpoint_data.dict().items() if v is not None}
            
            if not update_data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No valid fields provided for update"
                )
            
            response = self.supabase.table("endpoints").update(update_data).eq("id", str(endpoint_id)).execute()
            
            if not response.data:
                return None
            
            return EndpointResponse(**response.data[0])
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update endpoint: {str(e)}"
            )


    async def delete_endpoint(self, endpoint_id: UUID, user_id: str) -> bool:
        """Delete an endpoint"""
        try:
            # Validate ownership first by getting the endpoint
            existing_endpoint = await self.get_endpoint(endpoint_id, user_id)
            if not existing_endpoint:
                return False
            
            # Delete the endpoint
            response = self.supabase.table("endpoints").delete().eq("id", str(endpoint_id)).execute()

            if response.data:
                from app.db.redis import cache

                dashboard_pattern = f"dashboard:get_dashboard_data:{user_id}:*"
                await cache.delete_pattern(dashboard_pattern)
                workspace_key = f"workspace_stats:get_workspace_stats:{existing_endpoint.workspace_id}:{user_id}"
                await cache.delete(workspace_key)
                print(f"🗑️ Deleted endpoint and cleared cache: {dashboard_pattern}, {workspace_key}")

                return True

            return False
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete endpoint: {str(e)}"
            )

    async def test_endpoint(self, endpoint_id: UUID, user_id: str) -> dict:
        """Test an endpoint and return response data"""
        # Get endpoint to validate ownership
        endpoint = await self.get_endpoint(endpoint_id, user_id)
        if not endpoint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Endpoint not found"
            )
        
        try:
            import aiohttp
            import time
            
            start_time = time.time()
            
            # Prepare request data
            headers = endpoint.headers or {}
            # print(endpoint.body)

            if not headers.get('User-Agent'):
                headers['User-Agent'] = "Lookout/1.0"
            timeout = aiohttp.ClientTimeout(total=endpoint.timeout_seconds)

                        
            request_config = {
            "url": endpoint.url,
            "method": endpoint.method,
            "headers": headers, 
            "body": endpoint.body if endpoint.body else None,
            "timeout_seconds": endpoint.timeout_seconds
            }

            # print(request_config)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method=endpoint.method,
                    url=endpoint.url,
                    headers=headers,
                    data=endpoint.body if endpoint.body else None
                ) as response:
                    response_time = int((time.time() - start_time) * 1000)  # milliseconds
                    
                    return {
                        "status_code": response.status,
                        "response_time_ms": response_time,
                        "success": response.status == endpoint.expected_status,
                        "expected_status": endpoint.expected_status,
                        "headers": dict(response.headers),
                        "url": endpoint.url,
                        "method": endpoint.method,
                        "request_config": request_config
                    }
                    
        except Exception as e:
            return {
                "status_code": 0,
                "response_time_ms": 0,
                "success": False,
                "error": str(e),
                "expected_status": endpoint.expected_status,
                "url": endpoint.url,
                "method": endpoint.method,
                "request_config": request_config
            }