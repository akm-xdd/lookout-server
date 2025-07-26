# app/services/workspace_service.py
from fastapi import Depends, HTTPException, status
from supabase import Client
from typing import List, Optional
from uuid import UUID

from app.db.supabase import get_supabase
from app.schemas.workspace import WorkspaceCreate, WorkspaceUpdate, WorkspaceResponse
from app.core.constants import MAX_WORKSPACES_PER_USER


class WorkspaceService:
    def __init__(self, supabase: Client = Depends(get_supabase)):
        self.supabase = supabase

    async def _get_user_workspace_count(self, user_id: str) -> int:
        """Get the current number of workspaces for a user"""
        try:
            response = self.supabase.table("workspaces").select(
                "id", count="exact").eq("user_id", user_id).execute()
            return response.count or 0
        except Exception:
            return 0

    async def _validate_workspace_limit(self, user_id: str) -> None:
        """Validate that user hasn't exceeded workspace limit"""
        current_count = await self._get_user_workspace_count(user_id)

        if current_count >= MAX_WORKSPACES_PER_USER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Maximum {MAX_WORKSPACES_PER_USER} workspaces allowed per user. You currently have {current_count}."
            )

    async def _validate_workspace_name_unique(self, name: str, user_id: str, exclude_id: Optional[UUID] = None) -> None:
        """Validate that workspace name is unique for the user"""
        try:
            query = self.supabase.table("workspaces").select(
                "id").eq("user_id", user_id).eq("name", name)

            if exclude_id:
                query = query.neq("id", str(exclude_id))

            response = query.execute()

            if response.data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"You already have a workspace named '{name}'. Please choose a different name."
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service temporarily unavailable. Please try again. " + str(e)
            )

    async def get_user_workspaces(self, user_id: str) -> List[WorkspaceResponse]:
        """Get all workspaces for a user"""
        try:
            response = self.supabase.table("workspaces").select(
                "*").eq("user_id", user_id).order("created_at", desc=False).execute()
            if response.data is None:
                return []
            return [WorkspaceResponse(**workspace) for workspace in response.data]
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch workspaces: {str(e)}"
            )

    async def create_workspace(self, workspace_data: WorkspaceCreate, user_id: str) -> WorkspaceResponse:
        """Create a new workspace with validation"""
        # Validate workspace limit
        await self._validate_workspace_limit(user_id)

        # Validate unique name
        await self._validate_workspace_name_unique(workspace_data.name, user_id)

        try:
            data = {
                "name": workspace_data.name,
                "description": workspace_data.description,
                "user_id": user_id
            }

            response = self.supabase.table("workspaces").insert(data).execute()

            if response.data:
                from app.db.redis import cache
                # Clear any cached stats for this user
                dashboard_pattern = f"dashboard:get_dashboard_data:{user_id}:*"
                await cache.delete_pattern(dashboard_pattern)
                print(f"✅ Created workspace and cleared cache: {dashboard_pattern}")

                workspace_key = f"workspace_stats:get_workspace_stats:{response.data[0]['id']}:{user_id}"
                await cache.delete(workspace_key)
                print(f"✅ Cleared workspace cache: {workspace_key}")

            if not response.data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to create workspace"
                )

            return WorkspaceResponse(**response.data[0])

        except HTTPException:
            raise
        except Exception as e:
            if "duplicate key" in str(e).lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Workspace with this name already exists"
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create workspace: {str(e)}"
            )

    async def get_workspace(self, workspace_id: UUID, user_id: str) -> Optional[WorkspaceResponse]:
        """Get a specific workspace"""
        try:
            response = self.supabase.table("workspaces").select(
                "*").eq("id", str(workspace_id)).eq("user_id", user_id).execute()

            if not response.data:
                return None

            return WorkspaceResponse(**response.data[0])
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch workspace: {str(e)}"
            )

    async def update_workspace(self, workspace_id: UUID, workspace_data: WorkspaceUpdate, user_id: str) -> Optional[WorkspaceResponse]:
        """Update a workspace with validation"""
        # Validate unique name if name is being updated
        if workspace_data.name:
            await self._validate_workspace_name_unique(workspace_data.name, user_id, workspace_id)

        try:
            # Only include non-None values in update
            update_data = {k: v for k,
                           v in workspace_data.dict().items() if v is not None}

            if not update_data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No valid fields provided for update"
                )

            update_data["updated_at"] = "NOW()"

            response = self.supabase.table("workspaces").update(update_data).eq(
                "id", str(workspace_id)).eq("user_id", user_id).execute()

            if not response.data:
                return None

            return WorkspaceResponse(**response.data[0])

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update workspace: {str(e)}"
            )

    async def delete_workspace(self, workspace_id: UUID, user_id: str) -> bool:
        """Delete a workspace and all associated endpoints"""
        try:
            # Check if workspace exists and belongs to user
            workspace = await self.get_workspace(workspace_id, user_id)
            if not workspace:
                return False

            # Delete the workspace (endpoints will be deleted via CASCADE)
            response = self.supabase.table("workspaces").delete().eq(
                "id", str(workspace_id)).eq("user_id", user_id).execute()
            
            if response.data:
                from app.db.redis import cache
                # Clear any cached stats for this workspace
                workspace_key = f"workspace_stats:get_workspace_stats:{workspace_id}:{user_id}"
                await cache.delete(workspace_key)
                print(f"✅ Deleted workspace and cleared cache: {workspace_key}")

                dashboard_pattern = f"dashboard:get_dashboard_data:{user_id}:*"
                await cache.delete_pattern(dashboard_pattern)
                print(f"✅ Cleared dashboard cache: {dashboard_pattern}")

            return len(response.data) > 0

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete workspace: {str(e)}"
            )

    async def get_workspace_stats(self, workspace_id: UUID, user_id: str) -> dict:
        """Get workspace statistics including endpoint count"""
        try:
            # Get endpoint count for the workspace
            endpoint_response = self.supabase.table("endpoints").select(
                "id", count="exact").eq("workspace_id", str(workspace_id)).execute()
            endpoint_count = endpoint_response.count or 0

            # Get active endpoint count
            active_response = self.supabase.table("endpoints").select("id", count="exact").eq(
                "workspace_id", str(workspace_id)).eq("is_active", True).execute()
            active_count = active_response.count or 0

            return {
                "endpoint_count": endpoint_count,
                "active_endpoints": active_count,
                "max_endpoints": MAX_WORKSPACES_PER_USER,
                "can_add_endpoints": endpoint_count < MAX_WORKSPACES_PER_USER
            }

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get workspace stats: {str(e)}"
            )
