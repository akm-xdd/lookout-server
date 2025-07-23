# app/core/auth.py
import time
import jwt
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import Client
from app.db.supabase import get_supabase_admin, get_supabase
from typing import Dict, Any

security = HTTPBearer()

def validate_jwt_expiry(token: str) -> None:
    """Validate JWT token expiry without full signature verification."""
    try:
        # Decode without verification to check expiry
        decoded = jwt.decode(token, options={"verify_signature": False})
        
        exp = decoded.get('exp')
        if exp is None:
            return
        
        current_time = int(time.time())
        if exp < current_time:
            expired_seconds = current_time - exp
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token expired {expired_seconds} seconds ago. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        # Check if token expires within 30 seconds for proactive refresh
        time_until_expiry = exp - current_time
        if time_until_expiry < 30:
            pass  # Client can check this header and refresh proactively
            
    except jwt.DecodeError:
        pass
    except HTTPException:
        raise
    except Exception:
        pass

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict[str, Any]:
    """Extract and validate user from Supabase JWT token."""
    try:
        validate_jwt_expiry(credentials.credentials)
        
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
            "jwt_token": credentials.credentials,
        }
    
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e).lower()
        
        if any(keyword in error_msg for keyword in ['token', 'jwt', 'expired', 'invalid', 'unauthorized']):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token is invalid or expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        elif any(keyword in error_msg for keyword in ['connection', 'network', 'timeout', 'database']):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service temporarily unavailable",
                headers={"WWW-Authenticate": "Bearer"},
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication failed due to server error",
                headers={"WWW-Authenticate": "Bearer"},
            )

def get_user_id(current_user: Dict[str, Any] = Depends(get_current_user)) -> str:
    """Extract user ID from authenticated user"""
    return current_user["id"]

async def get_user_email(user_id: str = Depends(get_user_id)) -> str:
    """Extract user email from JWT token or fetch from Supabase."""
    try:
        supabase: Client = Depends(get_supabase)
        user_response = supabase.auth.admin.get_user_by_id(user_id)
        
        if user_response and user_response.user and user_response.user.email:
            return user_response.user.email
        
        return f"user-{user_id}@example.com"
        
    except Exception:
        return f"user-{user_id}@example.com"
