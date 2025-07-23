from supabase import create_client, Client
from supabase.lib.client_options import ClientOptions
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings


security = HTTPBearer()


def get_supabase_admin() -> Client:
    """Get Supabase client with service key (admin access)"""
    return create_client(
        settings.supabase_url,
        settings.supabase_service_key
    )


def get_supabase_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Client:
    """Get Supabase client with user's JWT token (respects RLS)"""
    # Create client options with proper structure
    options = ClientOptions(
        headers={
            "Authorization": f"Bearer {credentials.credentials}"
        }
    )
    
    return create_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        options=options
    )


# Backward compatibility - use user client by default
def get_supabase(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Client:
    """Get Supabase client with user authentication (default)"""
    return get_supabase_user(credentials)