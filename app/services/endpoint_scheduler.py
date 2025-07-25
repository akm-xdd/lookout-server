import asyncio
import time
import sys
from typing import Dict, List, Tuple, Optional, Any
from uuid import UUID
import aiohttp
from supabase import Client

from app.core.config import settings
from app.core.logging import SchedulerLogger
from app.services.health_monitor import SystemHealthMonitor


class EndpointScheduler:
    """
    Event-driven endpoint monitoring scheduler.
    
    Key features:
    - In-memory cache of endpoint configurations (event-driven updates)
    - Zero database reads during normal operation
    - Concurrent worker pool for HTTP checks
    - Circuit breaker integration for reliability
    - Precise scheduling based on endpoint frequency
    
    Architecture:
    1. Cache: endpoint_id → {config, next_check_time}
    2. Queue: (endpoint_id, scheduled_time) tuples
    3. Workers: Process queue items and perform HTTP checks
    4. Health Monitor: Circuit breaker for system failures
    """
    
    def __init__(self, supabase_client: Client):
        from app.db.supabase import get_supabase_admin

        self.supabase = get_supabase_admin()
        self.logger = SchedulerLogger()
        
        # Core state
        self.endpoint_cache: Dict[str, Dict[str, Any]] = {}
        self.check_queue: asyncio.Queue = asyncio.Queue()
        self.is_initialized: bool = False
        self.is_running: bool = False
        
        # Configuration
        self.worker_count = settings.worker_count
        self.scheduler_interval = settings.scheduler_interval
        self.http_timeout = settings.http_timeout
        self.retry_delay = settings.retry_delay
        
        # Components
        self.health_monitor: Optional[SystemHealthMonitor] = None
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.worker_tasks: List[asyncio.Task] = []
        self.scheduler_task: Optional[asyncio.Task] = None
        
        self.logger.logger.info(
            "Scheduler created",
            worker_count=self.worker_count,
            scheduler_interval=self.scheduler_interval,
            http_timeout=self.http_timeout
        )
    
    async def initialize(self) -> None:
        """
        Initialize the scheduler system.
        
        This is the ONLY time we read from the database.
        All subsequent updates come via events.
        """
        if self.is_initialized:
            self.logger.logger.warning("Scheduler already initialized")
            return
        
        try:
            # Initialize health monitor
            self.health_monitor = SystemHealthMonitor(self.supabase)
            await self.health_monitor.initialize()
            
            # Initialize HTTP session
            await self._initialize_http_session()
            
            # Load all active endpoints from database (one-time read)
            await self._load_endpoints_from_database()
            
            self.is_initialized = True
            
            cache_size_mb = sys.getsizeof(self.endpoint_cache) / (1024 * 1024)
            self.logger.startup(
                endpoint_count=len(self.endpoint_cache),
                cache_size_mb=cache_size_mb
            )
            
        except Exception as e:
            self.logger.critical("Failed to initialize scheduler", error=str(e))
            raise
    
    async def start(self) -> None:
        """Start the scheduler and worker pool"""
        if not self.is_initialized:
            raise RuntimeError("Scheduler must be initialized before starting")
        
        if self.is_running:
            self.logger.logger.warning("Scheduler already running")
            return
        
        try:
            self.is_running = True
            
            # Start worker pool
            self.worker_tasks = [
                asyncio.create_task(self._worker(worker_id))
                for worker_id in range(self.worker_count)
            ]
            
            # Start scheduler loop
            self.scheduler_task = asyncio.create_task(self._scheduler_loop())
            
            self.logger.logger.info(
                "Scheduler started",
                workers=len(self.worker_tasks),
                endpoints_loaded=len(self.endpoint_cache)
            )
            
        except Exception as e:
            self.logger.critical("Failed to start scheduler", error=str(e))
            await self.stop()
            raise
    
    async def stop(self) -> None:
        """Stop the scheduler and clean up resources"""
        self.is_running = False
        
        # Cancel scheduler loop
        if self.scheduler_task and not self.scheduler_task.done():
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                pass
        
        # Cancel all workers
        for task in self.worker_tasks:
            if not task.done():
                task.cancel()
        
        if self.worker_tasks:
            await asyncio.gather(*self.worker_tasks, return_exceptions=True)
        
        # Close HTTP session
        if self.http_session:
            await self.http_session.close()
        
        # Close health monitor
        if self.health_monitor:
            await self.health_monitor.close()
        
        self.logger.logger.info("Scheduler stopped")
    
    # Event handlers (called by API operations)
    
    def on_endpoint_created(self, endpoint_data: Dict[str, Any]) -> None:
        """Handle new endpoint creation (called by API)"""
        endpoint_id = str(endpoint_data['id'])
        
        # Calculate next check time - start checking immediately for new endpoints
        frequency_seconds = endpoint_data.get('frequency_minutes', 5) * 60
        next_check = time.time() + 10  # Start checking in 10 seconds for new endpoints
        
        # Add to cache
        cache_entry = {
            **endpoint_data,
            'next_check_time': next_check
        }
        
        self.endpoint_cache[endpoint_id] = cache_entry
        
        self.logger.cache_update(
            operation="CREATE",
            endpoint_id=endpoint_id,
            endpoint_name=endpoint_data.get('name', 'Unknown')
        )
        
        # Log immediate scheduling for new endpoints
        self.logger.logger.info(
            "New endpoint will be checked soon",
            endpoint_id=endpoint_id,
            endpoint_name=endpoint_data.get('name', 'Unknown'),
            next_check_in_seconds=10
        )
        
        # Check cache size warning
        if len(self.endpoint_cache) > settings.cache_warning_size:
            self.logger.cache_warning(
                cache_size=len(self.endpoint_cache),
                threshold=settings.cache_warning_size
            )
    
    def on_endpoint_updated(self, endpoint_id: str, updated_data: Dict[str, Any]) -> None:
        """Handle endpoint updates (called by API)"""
        if endpoint_id not in self.endpoint_cache:
            self.logger.logger.warning(
                "Attempted to update non-existent endpoint",
                endpoint_id=endpoint_id
            )
            return
        
        # Update cache entry
        cache_entry = self.endpoint_cache[endpoint_id]
        cache_entry.update(updated_data)
        
        # If frequency changed, recalculate next check time
        if 'frequency_minutes' in updated_data:
            frequency_seconds = updated_data['frequency_minutes'] * 60
            cache_entry['next_check_time'] = time.time() + frequency_seconds
        
        self.logger.cache_update(
            operation="UPDATE",
            endpoint_id=endpoint_id,
            endpoint_name=cache_entry.get('name', 'Unknown')
        )
    
    def on_endpoint_deleted(self, endpoint_id: str) -> None:
        """Handle endpoint deletion (called by API)"""
        if endpoint_id in self.endpoint_cache:
            endpoint_name = self.endpoint_cache[endpoint_id].get('name', 'Unknown')
            del self.endpoint_cache[endpoint_id]
            
            self.logger.cache_update(
                operation="DELETE",
                endpoint_id=endpoint_id,
                endpoint_name=endpoint_name
            )
        else:
            self.logger.logger.warning(
                "Attempted to delete non-existent endpoint",
                endpoint_id=endpoint_id
            )
    
    # Core scheduling logic
    
    async def _scheduler_loop(self) -> None:
        """Main scheduler loop - finds due endpoints and queues them"""
        self.logger.logger.info("Scheduler loop started")
        
        while self.is_running:
            try:
                # Check system health first
                if self.health_monitor:
                    is_healthy = await self.health_monitor.check_system_health()
                    if not is_healthy:
                        self.logger.logger.warning("System unhealthy, skipping scheduling cycle")
                        await asyncio.sleep(self.scheduler_interval)
                        continue
                
                # Check for queue overwhelm
                queue_size = self.check_queue.qsize()
                if self.health_monitor and self.health_monitor.is_queue_overwhelmed(queue_size):
                    self.logger.logger.warning("Queue overwhelmed, skipping scheduling cycle")
                    await asyncio.sleep(self.scheduler_interval)
                    continue
                
                # Find due endpoints
                due_endpoints = self._find_due_endpoints()
                
                # Queue due endpoints
                for endpoint_id, scheduled_time in due_endpoints:
                    await self.check_queue.put((endpoint_id, scheduled_time))
                    self.logger.check_queued(endpoint_id, self.check_queue.qsize())
                
                if due_endpoints:
                    self.logger.logger.info(
                        "Scheduled endpoint checks",
                        count=len(due_endpoints),
                        queue_size=self.check_queue.qsize()
                    )
                
            except Exception as e:
                self.logger.error("Error in scheduler loop", error=str(e))
            
            # Wait for next cycle
            await asyncio.sleep(self.scheduler_interval)
        
        self.logger.logger.info("Scheduler loop stopped")
        
    def _find_due_endpoints(self) -> List[Tuple[str, float]]:
        current_time = time.time()
        due_endpoints = []
        
        for endpoint_id, cache_entry in self.endpoint_cache.items():
            if not cache_entry.get('is_active', True):
                continue
            
            next_check_time = cache_entry.get('next_check_time', 0)
            
            # DEBUG: Show when endpoint will be checked
            print(f"🔍 Endpoint {endpoint_id[:8]}... next check in {next_check_time - current_time:.0f} seconds")
            
            if current_time >= next_check_time:
                due_endpoints.append((endpoint_id, next_check_time))
                # Update next check time
                frequency_seconds = cache_entry.get('frequency_minutes', 5) * 60
                cache_entry['next_check_time'] = current_time + frequency_seconds
        
        return due_endpoints
    
    async def _worker(self, worker_id: int) -> None:
        """Worker that processes the check queue"""
        self.logger.logger.info("Worker started", worker_id=worker_id)
        
        while self.is_running:
            try:
                # Get next item from queue (with timeout to allow shutdown)
                try:
                    endpoint_id, scheduled_time = await asyncio.wait_for(
                        self.check_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Process the check
                await self._check_endpoint_with_retry(endpoint_id, worker_id)
                
                # Mark task done
                self.check_queue.task_done()
                
            except Exception as e:
                self.logger.error(
                    "Worker error",
                    worker_id=worker_id,
                    error=str(e)
                )
        
        self.logger.logger.info("Worker stopped", worker_id=worker_id)
    
    async def _check_endpoint_with_retry(self, endpoint_id: str, worker_id: int) -> None:
        """Check an endpoint with retry logic"""
        # Get endpoint config from cache
        if endpoint_id not in self.endpoint_cache:
            self.logger.logger.warning(
                "Endpoint not found in cache",
                endpoint_id=endpoint_id,
                worker_id=worker_id
            )
            return
        
        endpoint_config = self.endpoint_cache[endpoint_id]
        
        # First attempt
        result = await self._perform_http_check(endpoint_config, worker_id)
        
        # Retry on failure
        if not result['success'] and result.get('retryable', True):
            self.logger.check_failed(
                endpoint_id=endpoint_id,
                error=result.get('error', 'Unknown error'),
                attempt=1
            )
            
            await asyncio.sleep(self.retry_delay)
            result = await self._perform_http_check(endpoint_config, worker_id, attempt=2)
        
        # Log result
        self.logger.check_completed(
            endpoint_id=endpoint_id,
            success=result['success'],
            response_time_ms=result['response_time_ms'],
            status_code=result.get('status_code')
        )
        
        # Save result to database
        await self._save_check_result(endpoint_id, result)
    
    async def _perform_http_check(self, endpoint_config: Dict[str, Any], worker_id: int, attempt: int = 1) -> Dict[str, Any]:
        """Perform the actual HTTP check"""
        start_time = time.time()
        
        try:
            # Prepare request
            url = endpoint_config['url']
            method = endpoint_config.get('method', 'GET')
            headers = endpoint_config.get('headers', {})
            body = endpoint_config.get('body')
            expected_status = endpoint_config.get('expected_status', 200)
            timeout_seconds = endpoint_config.get('timeout_seconds', self.http_timeout)
            
            # Add user agent if not specified
            if 'User-Agent' not in headers:
                headers['User-Agent'] = f'LookOut-Monitor/1.0 (Worker-{worker_id})'
            
            # Create timeout
            timeout = aiohttp.ClientTimeout(total=timeout_seconds)
            
            # Perform request
            async with self.http_session.request(
                method=method,
                url=url,
                headers=headers,
                data=body if body else None,
                timeout=timeout
            ) as response:
                response_time_ms = int((time.time() - start_time) * 1000)
                
                return {
                    'success': response.status == expected_status,
                    'status_code': response.status,
                    'response_time_ms': response_time_ms,
                    'expected_status': expected_status,
                    'attempt': attempt,
                    'retryable': True
                }
        
        except asyncio.TimeoutError:
            response_time_ms = int((time.time() - start_time) * 1000)
            return {
                'success': False,
                'error': 'Request timeout',
                'response_time_ms': response_time_ms,
                'attempt': attempt,
                'retryable': True
            }
        
        except Exception as e:
            response_time_ms = int((time.time() - start_time) * 1000)
            error_str = str(e)
            
            # Determine if error is retryable
            retryable = not any(non_retryable in error_str.lower() for non_retryable in [
                'name or service not known',
                'no address associated with hostname',
                'invalid url',
                'unsupported protocol'
            ])
            
            return {
                'success': False,
                'error': error_str,
                'response_time_ms': response_time_ms,
                'attempt': attempt,
                'retryable': retryable
            }
    
    async def _save_check_result(self, endpoint_id: str, result: Dict[str, Any]) -> None:
        """Save check result to database AND update last_check_at (simple version)"""
        try:
            print(f"🔄 Saving check result for endpoint {endpoint_id}")
            print(f"📊 Result: success={result['success']}, status={result.get('status_code')}, time={result['response_time_ms']}ms")
            
            # Step 1: Insert check result
            check_data = {
                'endpoint_id': endpoint_id,
                'status_code': result.get('status_code'),
                'response_time_ms': result['response_time_ms'],
                'success': result['success'],
                'error_message': result.get('error'),
                'checked_at': 'NOW()'
            }
            
            print(f"🔄 Inserting check result...")
            insert_result = self.supabase.table('check_results').insert(check_data).execute()
            print(f"✅ Check result inserted successfully")
            
            # Step 2: Update endpoint last_check_at
            consecutive_failures = 0 if result['success'] else (
                self.endpoint_cache.get(endpoint_id, {}).get('consecutive_failures', 0) + 1
            )
            
            print(f"🔄 Updating endpoint last_check_at and consecutive_failures={consecutive_failures}")
            
            update_data = {
                'last_check_at': 'NOW()',
                'consecutive_failures': consecutive_failures
            }
            
            update_result = self.supabase.table('endpoints').update(update_data).eq('id', endpoint_id).execute()
            print(f"✅ Endpoint updated successfully: {update_result.data}")
            
            # Step 3: Update cache
            if endpoint_id in self.endpoint_cache:
                self.endpoint_cache[endpoint_id]['consecutive_failures'] = consecutive_failures
                print(f"📝 Cache updated")
            
            self.logger.logger.info(
                "Check result and endpoint updated successfully",
                endpoint_id=endpoint_id,
                success=result['success'],
                consecutive_failures=consecutive_failures
            )
            
        except Exception as e:
            erro_str = str(e)
            if 'check_results_endpoint_id_fkey' in erro_str:
                if endpoint_id in self.endpoint_cache:
                    del self.endpoint_cache[endpoint_id]
                    print(f"🗑️ Removed deleted endpoint {endpoint_id} from cache")
                return
            self.logger.error(
                "Failed to save check result",
                endpoint_id=endpoint_id,
                error=erro_str
            )

    async def _save_check_result_fallback(self, endpoint_id: str, result: Dict[str, Any]) -> None:
        """Fallback method using separate queries"""
        try:
            # Insert check result
            check_data = {
                'endpoint_id': endpoint_id,
                'status_code': result.get('status_code'),
                'response_time_ms': result['response_time_ms'],
                'success': result['success'],
                'error_message': result.get('error'),
                'checked_at': 'NOW()'
            }
            
            self.supabase.table('check_results').insert(check_data).execute()
            
            # Update endpoint
            consecutive_failures = 0 if result['success'] else (
                self.endpoint_cache.get(endpoint_id, {}).get('consecutive_failures', 0) + 1
            )
            
            self.supabase.table('endpoints').update({
                'last_check_at': 'NOW()',
                'consecutive_failures': consecutive_failures
            }).eq('id', endpoint_id).execute()
            
            # Update cache
            if endpoint_id in self.endpoint_cache:
                self.endpoint_cache[endpoint_id]['consecutive_failures'] = consecutive_failures
            
        except Exception as e:
            self.logger.error(
                "Failed to save check result (fallback)",
                endpoint_id=endpoint_id,
                error=str(e)
            )

    async def _initialize_http_session(self) -> None:
        """Initialize the HTTP session for endpoint checks"""
        connector = aiohttp.TCPConnector(
            limit=self.worker_count * 2,  # Connection pool size
            limit_per_host=10,
            ttl_dns_cache=300,
            use_dns_cache=True,
            enable_cleanup_closed=True
        )
        
        timeout = aiohttp.ClientTimeout(total=self.http_timeout)
        
        self.http_session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                'User-Agent': 'LookOut-Monitor/1.0'
            }
        )
        
        self.logger.logger.info("HTTP session initialized", pool_size=self.worker_count * 2)
    
    async def _load_endpoints_from_database(self) -> None:
        """Load all active endpoints from database (one-time startup operation)"""
        try:
            
            
            # Test active query
            response = self.supabase.table('endpoints').select('*').eq('is_active', True).execute()
            
            current_time = time.time()
            
            for endpoint_data in response.data:
                endpoint_id = str(endpoint_data['id'])
                
                # Calculate next check time
                frequency_seconds = endpoint_data.get('frequency_minutes', 5) * 60
                next_check = current_time + frequency_seconds
                
                # Add to cache
                cache_entry = {
                    **endpoint_data,
                    'next_check_time': next_check
                }
                
                self.endpoint_cache[endpoint_id] = cache_entry
            
            self.logger.logger.info(
                "Loaded endpoints from database",
                count=len(self.endpoint_cache)
            )
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            self.logger.critical("Failed to load endpoints from database", error=str(e))
            raise
    
    def get_status(self) -> Dict[str, Any]:
        """Get current scheduler status for monitoring/debugging"""
        return {
            "is_running": self.is_running,
            "is_initialized": self.is_initialized,
            "endpoint_count": len(self.endpoint_cache),
            "queue_size": self.check_queue.qsize(),
            "worker_count": len(self.worker_tasks),
            "health_monitor": self.health_monitor.get_health_status() if self.health_monitor else None
        }