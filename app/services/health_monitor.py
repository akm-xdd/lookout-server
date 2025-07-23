import asyncio
import time
from typing import Optional
import aiohttp
from supabase import Client

from app.core.config import settings
from app.core.logging import get_logger


class SystemHealthMonitor:
    """
    Circuit breaker pattern implementation for the scheduler system.
    
    Monitors system health and prevents operations during outages:
    - Database connectivity
    - Internet connectivity  
    - Queue overwhelm detection
    
    States:
    - HEALTHY: All systems operational, processing continues
    - UNHEALTHY: Issues detected, processing paused
    - RECOVERING: Testing recovery, limited operations
    """
    
    def __init__(self, supabase_client: Client):
        self.supabase = supabase_client
        self.logger = get_logger("health_monitor")
        
        # Health state
        self.is_system_healthy: bool = True
        self.consecutive_failures: int = 0
        self.consecutive_successes: int = 0
        self.last_health_check: float = 0
        self.last_failure_reason: Optional[str] = None
        
        # Configuration from settings
        self.failure_threshold = settings.failure_threshold
        self.success_threshold = settings.success_threshold
        self.check_interval = settings.health_check_interval
        self.queue_overwhelmed_size = settings.queue_overwhelmed_size
        
        # HTTP session for connectivity tests
        self.session: Optional[aiohttp.ClientSession] = None
        
        self.logger.info(
            "Health monitor initialized",
            failure_threshold=self.failure_threshold,
            success_threshold=self.success_threshold,
            check_interval=self.check_interval
        )
    
    async def initialize(self) -> None:
        """Initialize the health monitor and HTTP session"""
        connector = aiohttp.TCPConnector(
            limit=5,  # Small connection pool for health checks
            limit_per_host=2,
            ttl_dns_cache=300,
            use_dns_cache=True,
        )
        
        timeout = aiohttp.ClientTimeout(total=10)  # Quick health checks
        
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                'User-Agent': 'LookOut-HealthMonitor/1.0'
            }
        )
        
        self.logger.info("Health monitor session initialized")
    
    async def close(self) -> None:
        """Clean up resources"""
        if self.session:
            await self.session.close()
            self.logger.info("Health monitor session closed")
    
    async def check_system_health(self) -> bool:
        """
        Perform comprehensive system health check.
        
        Returns:
            bool: True if system is healthy, False otherwise
        """
        current_time = time.time()
        
        # Don't check too frequently
        if current_time - self.last_health_check < self.check_interval:
            return self.is_system_healthy
        
        self.last_health_check = current_time
        
        # Run all health checks
        checks = [
            ("database", self._test_database_connection()),
            ("internet", self._test_internet_connectivity()),
        ]
        
        failed_checks = []
        
        for check_name, check_coro in checks:
            try:
                success = await check_coro
                if not success:
                    failed_checks.append(check_name)
            except Exception as e:
                self.logger.error(f"Health check {check_name} raised exception", error=str(e))
                failed_checks.append(check_name)
        
        # Determine overall health
        is_healthy = len(failed_checks) == 0
        
        if is_healthy:
            await self._handle_success()
        else:
            await self._handle_failure(f"Failed checks: {', '.join(failed_checks)}")
        
        return self.is_system_healthy
    
    def is_queue_overwhelmed(self, queue_size: int) -> bool:
        """
        Check if the processing queue is overwhelmed.
        
        Args:
            queue_size: Current size of the processing queue
            
        Returns:
            bool: True if queue is overwhelmed
        """
        if queue_size >= self.queue_overwhelmed_size:
            self.logger.warning(
                "Queue overwhelmed",
                queue_size=queue_size,
                threshold=self.queue_overwhelmed_size
            )
            return True
        
        # Warn at 50% capacity
        warning_threshold = self.queue_overwhelmed_size // 2
        if queue_size >= warning_threshold:
            self.logger.warning(
                "Queue size approaching threshold",
                queue_size=queue_size,
                threshold=self.queue_overwhelmed_size,
                warning_at=warning_threshold
            )
        
        return False
    
    async def _test_database_connection(self) -> bool:
        """Test database connectivity with a simple query"""
        try:
            # Simple query to test connection
            response = self.supabase.table("workspaces").select("id").limit(1).execute()
            
            # Check if response is valid (even if empty)
            if hasattr(response, 'data') and response.data is not None:
                self.logger.debug("Database health check passed")
                return True
            else:
                self.logger.warning("Database health check failed - invalid response")
                return False
                
        except Exception as e:
            self.logger.warning("Database health check failed", error=str(e))
            return False
    
    async def _test_internet_connectivity(self) -> bool:
        """Test internet connectivity with a reliable external service"""
        if not self.session:
            self.logger.error("HTTP session not initialized for connectivity test")
            return False
        
        # Test multiple reliable endpoints
        test_urls = [
            "https://httpbin.org/status/200",
            "https://httpstat.us/200",
            "https://www.google.com",
        ]
        
        for url in test_urls:
            try:
                async with self.session.get(url) as response:
                    if response.status == 200:
                        self.logger.debug("Internet connectivity check passed", url=url)
                        return True
            except Exception as e:
                self.logger.debug("Internet connectivity test failed", url=url, error=str(e))
                continue
        
        self.logger.warning("All internet connectivity tests failed")
        return False
    
    async def _handle_success(self) -> None:
        """Handle a successful health check"""
        self.consecutive_failures = 0
        self.consecutive_successes += 1
        self.last_failure_reason = None
        
        # If we were unhealthy, check if we can recover
        if not self.is_system_healthy:
            if self.consecutive_successes >= self.success_threshold:
                self.is_system_healthy = True
                self.consecutive_successes = 0
                
                self.logger.info(
                    "System health recovered",
                    consecutive_successes=self.consecutive_successes,
                    success_threshold=self.success_threshold
                )
            else:
                self.logger.info(
                    "System health improving",
                    consecutive_successes=self.consecutive_successes,
                    needed_for_recovery=self.success_threshold
                )
    
    async def _handle_failure(self, reason: str) -> None:
        """Handle a failed health check"""
        self.consecutive_successes = 0
        self.consecutive_failures += 1
        self.last_failure_reason = reason
        
        # If we were healthy, check if we should become unhealthy
        if self.is_system_healthy:
            if self.consecutive_failures >= self.failure_threshold:
                self.is_system_healthy = False
                
                self.logger.error(
                    "System health degraded - entering circuit breaker mode",
                    consecutive_failures=self.consecutive_failures,
                    failure_threshold=self.failure_threshold,
                    reason=reason
                )
            else:
                self.logger.warning(
                    "System health check failed",
                    consecutive_failures=self.consecutive_failures,
                    failure_threshold=self.failure_threshold,
                    reason=reason
                )
        else:
            self.logger.debug(
                "System health check failed (already unhealthy)",
                consecutive_failures=self.consecutive_failures,
                reason=reason
            )
    
    def get_health_status(self) -> dict:
        """
        Get current health status for monitoring/debugging.
        
        Returns:
            dict: Current health status information
        """
        return {
            "is_healthy": self.is_system_healthy,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "last_health_check": self.last_health_check,
            "last_failure_reason": self.last_failure_reason,
            "thresholds": {
                "failure_threshold": self.failure_threshold,
                "success_threshold": self.success_threshold,
                "queue_overwhelmed_size": self.queue_overwhelmed_size,
            },
            "next_check_in": max(0, self.check_interval - (time.time() - self.last_health_check))
        }
    
    async def force_health_check(self) -> bool:
        """
        Force an immediate health check, bypassing the interval.
        Useful for testing or immediate status updates.
        
        Returns:
            bool: Current health status after check
        """
        self.last_health_check = 0  # Reset to force check
        return await self.check_system_health()