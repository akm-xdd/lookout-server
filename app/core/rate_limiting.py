import time
import asyncio
from typing import Dict, Optional, Tuple
from collections import defaultdict
from datetime import datetime, timedelta
import hashlib
from fastapi import HTTPException, status, Request
from fastapi.security import HTTPAuthorizationCredentials
import jwt

class RateLimiter:
    """
    Simple in-memory rate limiter with sliding window.
    Production-ready but minimal implementation.
    """
    
    def __init__(self):
        # Format: {key: [(timestamp, count), ...]}
        self.buckets: Dict[str, list] = defaultdict(list)
        self.last_cleanup = time.time()
        self.cleanup_interval = 300  # 5 minutes
        
        # Rate limiting rules: {endpoint_pattern: (requests, window_seconds)}
        self.rules = {
            # Critical endpoints (strict limits)
            'test_endpoint': (5, 60),       # 5 requests per minute per user
            'dashboard': (20, 60),          # 20 requests per minute per user
            'workspace_stats': (30, 60),    # 30 requests per minute per user
            
            # Creation endpoints (moderate limits)
            'create_workspace': (10, 300),  # 10 creations per 5 minutes per user
            'create_endpoint': (20, 300),   # 20 creations per 5 minutes per user
            
            # General API endpoints (lenient limits)
            'general_api': (100, 60),       # 100 requests per minute per user
            
            # Auth endpoints (per IP, not per user)
            'auth_attempts': (20, 300),     # 20 auth attempts per 5 minutes per IP

            # Health checks (very lenient)
            'scheduler_health_check': (3, 300)  # 3 health checks per 5 minutes per user
        }
        
        # Feature flag for gradual rollout
        self.enabled_percentage = 100  # Start at 100% for critical security
        self.log_only_mode = False     # Set to True for monitoring without blocking
        
    def _cleanup_old_entries(self) -> None:
        """Remove expired entries to prevent memory leaks"""
        current_time = time.time()
        
        # Only cleanup every 5 minutes to reduce overhead
        if current_time - self.last_cleanup < self.cleanup_interval:
            return
            
        cutoff_time = current_time - 3600  # Remove entries older than 1 hour
        
        for key in list(self.buckets.keys()):
            self.buckets[key] = [
                (timestamp, count) for timestamp, count in self.buckets[key]
                if timestamp > cutoff_time
            ]
            
            # Remove empty buckets
            if not self.buckets[key]:
                del self.buckets[key]
                
        self.last_cleanup = current_time
    
    def _get_rate_limit_key(self, identifier: str, endpoint_type: str) -> str:
        """Generate a unique key for rate limiting"""
        # Hash for privacy and consistent length
        combined = f"{endpoint_type}:{identifier}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]
    
    def _should_apply_rate_limit(self) -> bool:
        """Determine if rate limiting should be applied (for gradual rollout)"""
        if self.enabled_percentage >= 100:
            return True
        
        import random
        return random.random() * 100 < self.enabled_percentage
    
    async def check_rate_limit(
        self, 
        identifier: str, 
        endpoint_type: str,
        request_path: str = ""
    ) -> Tuple[bool, Optional[Dict]]:
        """
        Check if request should be rate limited.
        
        Returns: (allowed, rate_limit_info)
        """
        # Cleanup old entries periodically
        self._cleanup_old_entries()
        
        # Check if rate limiting should be applied
        if not self._should_apply_rate_limit():
            return True, None
        
        # Get rate limit rule
        rule = self.rules.get(endpoint_type, self.rules['general_api'])
        max_requests, window_seconds = rule
        
        # Generate rate limit key
        key = self._get_rate_limit_key(identifier, endpoint_type)
        
        current_time = time.time()
        window_start = current_time - window_seconds
        
        # Get requests in current window
        bucket = self.buckets[key]
        recent_requests = [
            (timestamp, count) for timestamp, count in bucket
            if timestamp > window_start
        ]
        
        # Calculate current request count
        current_count = sum(count for _, count in recent_requests)
        
        # Check if limit exceeded
        if current_count >= max_requests:
            # Calculate reset time
            oldest_request = min(recent_requests, key=lambda x: x[0])[0] if recent_requests else current_time
            reset_time = oldest_request + window_seconds
            
            rate_limit_info = {
                'limit': max_requests,
                'remaining': 0,
                'reset': int(reset_time),
                'window_seconds': window_seconds,
                'endpoint_type': endpoint_type
            }
            
            if self.log_only_mode:
                # Log but don't block
                print(f"RATE_LIMIT_EXCEEDED (log_only): {endpoint_type} - {identifier} - {current_count}/{max_requests}")
                return True, rate_limit_info
            
            return False, rate_limit_info
        
        # Add current request to bucket
        bucket.append((current_time, 1))
        self.buckets[key] = bucket
        
        # Calculate remaining requests
        remaining = max_requests - (current_count + 1)
        
        rate_limit_info = {
            'limit': max_requests,
            'remaining': remaining,
            'reset': int(current_time + window_seconds),
            'window_seconds': window_seconds,
            'endpoint_type': endpoint_type
        }
        
        return True, rate_limit_info

# Global rate limiter instance
rate_limiter = RateLimiter()

def get_client_identifier(request: Request, user_id: Optional[str] = None) -> str:
    """
    Get client identifier for rate limiting.
    Uses user_id if authenticated, otherwise IP address.
    """
    if user_id:
        return f"user:{user_id}"
    
    # Get client IP (handle proxies)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take first IP in chain
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"
    
    return f"ip:{client_ip}"

def extract_user_from_token(token: str) -> Optional[str]:
    """
    Extract user ID from JWT token without full validation.
    Used for rate limiting only.
    """
    try:
        decoded = jwt.decode(token, options={"verify_signature": False})
        return decoded.get('sub')  # 'sub' is the user ID in Supabase JWTs
    except Exception:
        return None

async def apply_rate_limit(
    request: Request,
    endpoint_type: str,
    credentials: Optional[HTTPAuthorizationCredentials] = None
) -> None:
    """
    Apply rate limiting to an endpoint.
    Raises HTTPException if rate limit exceeded.
    """
    # Get user ID if authenticated
    user_id = None
    if credentials:
        user_id = extract_user_from_token(credentials.credentials)
    
    # Get client identifier
    identifier = get_client_identifier(request, user_id)
    
    # Check rate limit
    allowed, rate_info = await rate_limiter.check_rate_limit(
        identifier, 
        endpoint_type,
        str(request.url)
    )
    
    if not allowed and rate_info:
        # Add rate limit headers to the exception
        headers = {
            "X-RateLimit-Limit": str(rate_info['limit']),
            "X-RateLimit-Remaining": str(rate_info['remaining']),
            "X-RateLimit-Reset": str(rate_info['reset']),
            "Retry-After": str(rate_info['window_seconds'])
        }
        
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for {endpoint_type}. Try again in {rate_info['window_seconds']} seconds.",
            headers=headers
        )

# Decorator for easy rate limiting application
def rate_limit(endpoint_type: str):
    """
    Decorator to apply rate limiting to FastAPI endpoints.
    
    Usage:
    @rate_limit("test_endpoint")
    async def test_endpoint(...):
        pass
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Find request and credentials in function parameters
            request = None
            credentials = None
            
            # Look for Request and HTTPAuthorizationCredentials in kwargs
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            
            for arg in args:
                if isinstance(arg, HTTPAuthorizationCredentials):
                    credentials = arg
                    break
            
            # Also check kwargs
            if not request:
                request = kwargs.get('request')
            if not credentials:
                credentials = kwargs.get('credentials')
            
            # Apply rate limiting
            if request:
                await apply_rate_limit(request, endpoint_type, credentials)
            
            # Call original function
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator

# Configuration for emergency controls
class RateLimitConfig:
    @staticmethod
    def emergency_disable():
        """Emergency disable rate limiting"""
        rate_limiter.enabled_percentage = 0
        print("🚨 RATE LIMITING EMERGENCY DISABLED")
    
    @staticmethod
    def enable_log_only_mode():
        """Enable log-only mode for monitoring"""
        rate_limiter.log_only_mode = True
        print("📊 RATE LIMITING SET TO LOG-ONLY MODE")
    
    @staticmethod
    def set_rollout_percentage(percentage: int):
        """Set rollout percentage (0-100)"""
        rate_limiter.enabled_percentage = max(0, min(100, percentage))
        print(f"⚙️ RATE LIMITING SET TO {percentage}%")
    
    @staticmethod
    def get_stats() -> Dict:
        """Get rate limiting statistics"""
        return {
            "enabled_percentage": rate_limiter.enabled_percentage,
            "log_only_mode": rate_limiter.log_only_mode,
            "active_buckets": len(rate_limiter.buckets),
            "rules": rate_limiter.rules
        }
