import json
import functools
from typing import Any, Callable
from app.db.redis import cache
from app.core.config import settings


def redis_cache(ttl: int = 300, key_prefix: str = ""):
    """
    Simple Redis cache decorator.
    
    Usage:
    @redis_cache(ttl=60, key_prefix="dashboard")
    async def my_function(user_id: str):
        # expensive operation
        return result
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Skip 'self' parameter for instance methods
            cache_args = args[1:] if args and hasattr(args[0], '__dict__') else args
            
            # Build cache key from function name and arguments (excluding self)
            cache_key_parts = [key_prefix, func.__name__] + [str(arg) for arg in cache_args]
            cache_key = ":".join(filter(None, cache_key_parts))
            
            print(f"🔍 Cache: Looking for key: {cache_key}")
            print(f"🔧 Redis enabled: {settings.redis_enabled}")
            
            # Try to get from cache
            try:
                cached_result = await cache.get(cache_key)
                if cached_result is not None:
                    print(f"✅ Cache HIT: {cache_key}")
                    return cached_result
                else:
                    print(f"❌ Cache MISS: {cache_key}")
            except Exception as e:
                print(f"⚠️ Cache get error: {e}")
            
            # Compute result
            print(f"🔄 Computing fresh data...")
            result = await func(*args, **kwargs)
            
            # Store in cache
            try:
                # Convert Pydantic models to dict for caching
                cache_data = result.dict() if hasattr(result, 'dict') else result
                success = await cache.set(cache_key, cache_data, ttl=ttl)
                print(f"💾 Cache set: {success} for key: {cache_key} (TTL: {ttl}s)")
            except Exception as e:
                print(f"⚠️ Cache set error: {e}")
            
            return result
        return wrapper
    return decorator