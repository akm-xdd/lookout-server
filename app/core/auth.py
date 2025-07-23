from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import Client
from app.db.supabase import get_supabase_admin, get_supabase
from typing import Dict, Any


security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict[str, Any]:
    """
    Extract and validate user from Supabase JWT token
    Uses admin client to validate token, but returns user info
    """
    try:
        # Use admin client to validate the JWT token
        supabase_admin = get_supabase_admin()
        user_response = supabase_admin.auth.get_user(credentials.credentials)
        
        if not user_response.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return {
            "id": user_response.user.id,
            "email": user_response.user.email,
            "user_metadata": user_response.user.user_metadata,
            "app_metadata": user_response.user.app_metadata,
            "jwt_token": credentials.credentials,  # Store the JWT for database operations
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_user_id(current_user: Dict[str, Any] = Depends(get_current_user)) -> str:
    """Extract user ID from authenticated user"""
    return current_user["id"]


async def get_user_email(user_id: str = Depends(get_user_id)) -> str:
    """
    Extract user email from JWT token or fetch from Supabase.
    This is needed for the dashboard endpoint.
    """
    try:
        # For now, we'll get it from Supabase auth
        # In production, you might want to extract it from JWT token directly
        supabase: Client = Depends(get_supabase)
        
        # Get user info from Supabase auth
        user_response = supabase.auth.admin.get_user_by_id(user_id)
        
        if user_response.user and user_response.user.email:
            return user_response.user.email
        
        # Fallback: try to decode from JWT token in request headers
        # This would require accessing the request headers
        return f"user-{user_id}@example.com"  # Temporary fallback
        
    except Exception:
        # Fallback email if we can't get the real one
        return f"user-{user_id}@example.com"