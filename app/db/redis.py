# app/db/redis.py
import redis.asyncio as redis
import json
import logging
from typing import Optional, Any, Union
from contextlib import asynccontextmanager

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global Redis connection pool
_redis_pool: Optional[redis.ConnectionPool] = None
_redis_client: Optional[redis.Redis] = None


async def get_redis_pool() -> redis.ConnectionPool:
    """Get or create Redis connection pool"""
    global _redis_pool
    
    if _redis_pool is None:
        if not settings.redis_enabled:
            raise RuntimeError("Redis is disabled in configuration")
        
        try:
            # Build connection kwargs
            connection_kwargs = {
                "max_connections": settings.redis_max_connections,
                "retry_on_timeout": True,
                "socket_timeout": 5,
                "socket_connect_timeout": 5,
                "health_check_interval": 30
            }
            
            # Add password if provided separately
            if settings.redis_password:
                connection_kwargs["password"] = settings.redis_password
            
            # For SSL connections, add SSL configuration
            if settings.redis_ssl:
                import ssl
                connection_kwargs["ssl_cert_reqs"] = None
                connection_kwargs["ssl_check_hostname"] = False
            
            # Ensure URL has proper protocol
            redis_url = settings.redis_url
            if not redis_url.startswith(("redis://", "rediss://")):
                redis_url = f"redis://{redis_url}"
            
            _redis_pool = redis.ConnectionPool.from_url(
                redis_url,
                **connection_kwargs
            )
            logger.info("Redis connection pool created successfully")
        except Exception as e:
            logger.error(f"Failed to create Redis connection pool: {e}")
            raise
    
    return _redis_pool


async def get_redis() -> redis.Redis:
    """Get Redis client instance"""
    global _redis_client
    
    if _redis_client is None:
        pool = await get_redis_pool()
        _redis_client = redis.Redis(connection_pool=pool, decode_responses=True)
        
        # Test connection
        try:
            await _redis_client.ping()
            logger.info("Redis connection established successfully")
        except Exception as e:
            logger.error(f"Redis connection test failed: {e}")
            raise
    
    return _redis_client


async def close_redis():
    """Close Redis connections"""
    global _redis_pool, _redis_client
    
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
    
    if _redis_pool:
        await _redis_pool.disconnect()
        _redis_pool = None
    
    logger.info("Redis connections closed")


@asynccontextmanager
async def redis_context():
    """Context manager for Redis operations with automatic cleanup"""
    client = None
    try:
        client = await get_redis()
        yield client
    except Exception as e:
        logger.error(f"Redis operation failed: {e}")
        raise
    finally:
        # Connection is returned to pool automatically
        pass


class RedisCache:
    """High-level Redis caching utilities"""
    
    def __init__(self):
        self.client: Optional[redis.Redis] = None
    
    async def _get_client(self) -> redis.Redis:
        """Get Redis client lazily"""
        if self.client is None:
            self.client = await get_redis()
        return self.client
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache with JSON deserialization"""
        if not settings.redis_enabled:
            return None
        
        try:
            client = await self._get_client()
            value = await client.get(key)
            
            if value is None:
                return None
            
            return json.loads(value)
        except Exception as e:
            logger.warning(f"Cache get failed for key {key}: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """Set value in cache with JSON serialization and TTL"""
        if not settings.redis_enabled:
            return False
        
        try:
            client = await self._get_client()
            serialized = json.dumps(value, default=str)  # default=str handles datetime objects
            await client.setex(key, ttl, serialized)
            return True
        except Exception as e:
            logger.warning(f"Cache set failed for key {key}: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if not settings.redis_enabled:
            return False
        
        try:
            client = await self._get_client()
            result = await client.delete(key)
            return result > 0
        except Exception as e:
            logger.warning(f"Cache delete failed for key {key}: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """Check if key exists in cache"""
        if not settings.redis_enabled:
            return False
        
        try:
            client = await self._get_client()
            result = await client.exists(key)
            return result > 0
        except Exception as e:
            logger.warning(f"Cache exists check failed for key {key}: {e}")
            return False
    
    async def health_check(self) -> bool:
        """Check Redis health"""
        if not settings.redis_enabled:
            return True  # Consider healthy if disabled
        
        try:
            client = await self._get_client()
            await client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False
    
    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a pattern"""
        if not settings.redis_enabled:
            return 0
        
        try:
            client = await self._get_client()
            keys = await client.keys(pattern)
            if keys:
                deleted = await client.delete(*keys)
                return deleted
            return 0
        except Exception as e:
            logger.warning(f"Cache pattern delete failed for pattern {pattern}: {e}")
            return 0
# Global cache instance
cache = RedisCache()


async def get_cache() -> RedisCache:
    """Dependency for FastAPI to get cache instance"""
    return cache