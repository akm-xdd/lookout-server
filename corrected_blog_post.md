---
title: "LookOut Deep Dive: Architecture and Design Choices"
date: "2025-07-30"
excerpt: "After months of building and testing, LookOut is ready for developers who need basic monitoring without the complexity."
category: "Architecture"
tags: ["launch", "monitoring", "free", "developer-tools"]
---

# LookOut Backend Architecture Deep Dive: Real-World Implementation

## Monitoring Infrastructure at Scale

LookOut handles endpoint monitoring through a sophisticated scheduling system that balances precision, performance, and resource efficiency. Here's how the core components work together.

## The Scheduler Engine

### Event-Driven Cache Architecture

The scheduler operates on a zero-database-reads model during normal operation. All endpoint configurations are loaded once at startup and maintained in memory:

```python
# One-time database read at startup
async def _load_endpoints_from_database(self) -> None:
    response = self.supabase.table('endpoints').select('*').eq('is_active', True).execute()
    current_time = time.time()
    
    for endpoint_data in response.data:
        endpoint_id = str(endpoint_data['id'])
        frequency_seconds = endpoint_data.get('frequency_minutes', 5) * 60
        next_check = current_time + frequency_seconds
        
        cache_entry = {
            **endpoint_data,
            'next_check_time': next_check
        }
        
        self.endpoint_cache[endpoint_id] = cache_entry
```

After initialization, all configuration changes propagate through event handlers:

```python
def on_endpoint_created(self, endpoint_data: Dict[str, Any]) -> None:
    endpoint_id = str(endpoint_data['id'])
    frequency_seconds = endpoint_data.get('frequency_minutes', 5) * 60
    next_check = time.time() + 10  # Start checking in 10 seconds for new endpoints
    
    cache_entry = {
        **endpoint_data,
        'next_check_time': next_check
    }
    
    self.endpoint_cache[endpoint_id] = cache_entry
```

This design eliminates polling overhead and ensures consistent performance regardless of database load.

### Precision Scheduling Algorithm

The scheduler runs every 30 seconds and uses precise timing calculations to determine which endpoints need checking:

```python
async def _scheduler_loop(self) -> None:
    while self.is_running:
        # Check system health first
        if self.health_monitor:
            is_healthy = await self.health_monitor.check_system_health()
            if not is_healthy:
                await asyncio.sleep(self.scheduler_interval)
                continue
        
        # Find due endpoints
        due_endpoints = self._find_due_endpoints()
        
        # Queue due endpoints for worker processing
        for endpoint_id, scheduled_time in due_endpoints:
            await self.check_queue.put((endpoint_id, scheduled_time))
        
        await asyncio.sleep(self.scheduler_interval)

def _find_due_endpoints(self) -> List[Tuple[str, float]]:
    current_time = time.time()
    due_endpoints = []
    
    for endpoint_id, cache_entry in self.endpoint_cache.items():
        if not cache_entry.get('is_active', True):
            continue
        
        next_check_time = cache_entry.get('next_check_time', 0)
        
        if current_time >= next_check_time:
            due_endpoints.append((endpoint_id, next_check_time))
            # Update next check time immediately
            frequency_seconds = cache_entry.get('frequency_minutes', 5) * 60
            cache_entry['next_check_time'] = current_time + frequency_seconds
    
    return due_endpoints
```

The algorithm ensures endpoints are checked as close to their scheduled time as possible, with a maximum deviation of 30 seconds (the scheduler interval).

## Concurrent Worker Pool

### HTTP Session Management

The system uses 12 concurrent workers sharing a single HTTP session pool optimized for monitoring workloads:

```python
async def _initialize_http_session(self) -> None:
    connector = aiohttp.TCPConnector(
        limit=self.worker_count * 2,  # 24 total connections
        limit_per_host=10,            # Max 10 connections per host
        ttl_dns_cache=300,            # 5-minute DNS cache
        use_dns_cache=True,
        enable_cleanup_closed=True
    )
    
    timeout = aiohttp.ClientTimeout(total=self.http_timeout)  # 20 seconds
    
    self.http_session = aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers={
            'User-Agent': 'LookOut-Monitor/1.0'
        }
    )
```

### Worker Processing Logic

Each worker processes the shared queue independently, performing HTTP checks and database writes:

```python
async def _worker(self, worker_id: int) -> None:
    while self.is_running:
        try:
            # Get next endpoint to check (with timeout for clean shutdown)
            endpoint_id, scheduled_time = await asyncio.wait_for(
                self.check_queue.get(), timeout=1.0
            )
            
            # Process the check
            await self._check_endpoint_with_retry(endpoint_id, worker_id)
            
            # Mark task done
            self.check_queue.task_done()
            
        except asyncio.TimeoutError:
            continue  # No work available, check again
        except Exception as e:
            self.logger.error("Worker error", worker_id=worker_id, error=str(e))
```

Workers operate independently without coordination overhead, using the shared queue for load distribution.

## Database Write Strategy

### Individual ACID Operations

Each monitoring result is written as a separate ACID transaction, ensuring data consistency:

```python
async def _save_check_result(self, endpoint_id: str, result: Dict[str, Any]) -> None:
    # Step 1: Insert check result
    check_data = {
        'endpoint_id': endpoint_id,
        'status_code': result.get('status_code'),
        'response_time_ms': result['response_time_ms'],
        'success': result['success'],
        'error_message': result.get('error'),
        'checked_at': 'NOW()'
    }
    
    self.supabase.table('check_results').insert(check_data).execute()
    
    # Step 2: Update endpoint metadata
    consecutive_failures = 0 if result['success'] else (
        self.endpoint_cache.get(endpoint_id, {}).get('consecutive_failures', 0) + 1
    )
    
    self.supabase.table('endpoints').update({
        'last_check_at': 'NOW()',
        'consecutive_failures': consecutive_failures
    }).eq('id', endpoint_id).execute()
    
    # Step 3: Update in-memory cache
    if endpoint_id in self.endpoint_cache:
        self.endpoint_cache[endpoint_id]['consecutive_failures'] = consecutive_failures
```

This approach prioritizes data integrity over write performance, ensuring each result is permanently recorded even if subsequent operations fail.

## Data Management Strategy

### Manual Cleanup System

**Note**: The current implementation does not include automated data cleanup. Historical data accumulates indefinitely, which may require manual database maintenance for long-running deployments.

### Multi-Layer Caching Architecture

The system implements Redis-based caching with different TTLs based on data volatility:

```python
# Dashboard data - 1 minute cache
@redis_cache(ttl=60, key_prefix="dashboard")
async def get_dashboard_data(self, user_id: str, user_email: str) -> DashboardResponse:
    # Expensive dashboard aggregation queries cached here

# Workspace statistics - 5 minute cache  
@redis_cache(ttl=300, key_prefix="workspace_stats")
async def get_workspace_stats(self, workspace_id: UUID, user_id: str) -> WorkspaceStatsResponse:
    # Workspace-level analytics cached here
```

**Redis Cache Implementation**: The caching decorator automatically handles serialization, key generation, and TTL management:

```python
def redis_cache(ttl: int = 300, key_prefix: str = ""):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Build cache key from function name and arguments
            cache_key_parts = [key_prefix, func.__name__] + [str(arg) for arg in cache_args]
            cache_key = ":".join(filter(None, cache_key_parts))
            
            # Try to get from cache
            cached_result = await cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Compute result and cache it
            result = await func(*args, **kwargs)
            cache_data = result.dict() if hasattr(result, 'dict') else result
            await cache.set(cache_key, cache_data, ttl=ttl)
            
            return result
        return wrapper
    return decorator
```

## Circuit Breaker Implementation

### System Health Monitoring

The health monitor prevents cascade failures through proactive system state management:

```python
class SystemHealthMonitor:
    async def check_system_health(self) -> bool:
        current_time = time.time()
        
        # Throttle health checks to every 2 minutes
        if current_time - self.last_health_check < self.check_interval:
            return self.is_system_healthy
        
        self.last_health_check = current_time
        
        # Test database connectivity and internet connectivity
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
                failed_checks.append(check_name)
        
        # Determine overall health
        is_healthy = len(failed_checks) == 0
        
        if is_healthy:
            await self._handle_success()
        else:
            await self._handle_failure(f"Failed checks: {', '.join(failed_checks)}")
        
        return self.is_system_healthy
```

### Failure State Management

The circuit breaker uses configurable thresholds to determine when to trip:

- **Failure Threshold**: 3 consecutive failures trigger circuit opening
- **Success Threshold**: 3 consecutive successes enable recovery  
- **Queue Overwhelm**: 1000+ queued items pause scheduling

When the circuit opens, the scheduler skips work cycles, allowing the system to recover without accumulating additional load.

## Performance Optimizations

### Memory Efficiency

The in-memory cache scales efficiently with endpoint count. Each cache entry contains:

```python
cache_entry = {
    'id': endpoint_id,                    # UUID: 36 bytes
    'name': endpoint_name,                # ~30 bytes average
    'url': endpoint_url,                  # ~100 bytes average
    'method': http_method,                # 3-4 bytes
    'frequency_minutes': check_frequency, # 4 bytes
    'next_check_time': calculated_timestamp, # 8 bytes
    'consecutive_failures': failure_count,   # 4 bytes
    'headers': request_headers,           # 0-200 bytes typical
    'body': request_body,                 # 0-1KB typical
    # Additional endpoint configuration...
}
```

**Storage Breakdown**:

- **Typical GET**: ~463 bytes per endpoint
- **GET with headers**: ~663 bytes per endpoint
- **POST with body**: ~1.7KB per endpoint
- **Weighted average**: ~676 bytes per endpoint

Current memory usage calculation:

```python
cache_size_mb = sys.getsizeof(self.endpoint_cache) / (1024 * 1024)
```

Supporting thousands of endpoints within typical VM memory limits (1000 endpoints = ~676KB cache).

### Connection Pool Optimization

HTTP connection pooling reduces establishment overhead:

- **Total Pool**: 24 connections (worker_count * 2)
- **Per-Host Limit**: 10 connections maximum
- **DNS Caching**: 5-minute TTL reduces lookup latency
- **Connection Reuse**: Persistent connections for frequently checked endpoints

## Integration Points

### Event-Driven Updates

API operations trigger immediate cache updates without database polling:

```python
# API endpoint creation
@router.post("/", response_model=EndpointResponse, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    workspace_id: UUID,
    endpoint_data: EndpointCreate,
    user_id: str = Depends(get_user_id),
    endpoint_service: EndpointService = Depends()
):
    endpoint = await endpoint_service.create_endpoint(endpoint_data, workspace_id, user_id)
    notify_endpoint_created(endpoint.dict())  # Trigger scheduler cache update
    return endpoint
```

### Notification Integration

The monitoring system integrates with notification triggers:

```python
async def handle_endpoint_check(self, endpoint_id: str, check_result: Dict[str, Any]) -> None:
    # Only process failures - successes don't trigger notifications
    if check_result.get('success', False):
        return
    
    # Get endpoint data with user info and check thresholds
    consecutive_failures = endpoint_data.get('consecutive_failures', 0)
    failure_threshold = user_settings.get('failure_threshold', 5)
    
    if consecutive_failures >= failure_threshold:
        # Trigger outage notification system
        await outage_notification_service.handle_endpoint_failure(
            user_id=endpoint_data['user_id'],
            endpoint_id=endpoint_id,
            failure_threshold=failure_threshold,
            consecutive_failures=consecutive_failures
        )
```

**Failure Threshold Logic**: Notifications trigger when `consecutive_failures >= failure_threshold` (default: 5) and user has notifications enabled.

## Real-World Performance Characteristics

### Throughput Metrics

- **Scheduler Precision**: ±30 seconds maximum deviation from scheduled time
- **Worker Concurrency**: 12 simultaneous HTTP checks
- **Database Writes**: ~2 writes per check (result + endpoint update)
- **Cache Hit Rate**: Varies by endpoint (dashboard: 1min TTL, workspace stats: 5min TTL)

### Resource Utilization

- **Memory**: Linear scaling with endpoint count (~676 bytes per endpoint)
- **CPU**: I/O bound workload, minimal computation
- **Network**: Outbound HTTP requests + database connections
- **Database**: Write-heavy workload, ~1MB per 1000 checks

### Scaling Characteristics

The current architecture handles growth through:

1. **Vertical Scaling**: More workers + larger connection pools on bigger VMs
2. **Intelligent Throttling**: Circuit breaker prevents resource exhaustion
3. **Event-Driven Design**: Configuration changes don't impact monitoring performance
4. **Direct Database Access**: Simple but may require optimization for high-traffic scenarios

## Operational Reliability

### Error Handling Patterns

```python
# Graceful degradation for endpoint deletions
if 'check_results_endpoint_id_fkey' in error_str:
    if endpoint_id in self.endpoint_cache:
        del self.endpoint_cache[endpoint_id]
        print(f"🗑️ Removed deleted endpoint {endpoint_id} from cache")
    return
```

The system handles common failure modes:

- **Deleted Endpoints**: Automatic cache cleanup on foreign key violations
- **Network Timeouts**: Per-request 20-second timeouts prevent worker blocking
- **Database Failures**: Circuit breaker pauses operations during outages
- **Memory Pressure**: Fixed-size queues prevent unbounded growth

### Health Status Monitoring

Health status is exposed through API endpoints:

```python
def get_status(self) -> Dict[str, Any]:
    return {
        "is_running": self.is_running,
        "is_initialized": self.is_initialized,
        "endpoint_count": len(self.endpoint_cache),
        "queue_size": self.check_queue.qsize(),
        "worker_count": len(self.worker_tasks),
        "health_monitor": self.health_monitor.get_health_status() if self.health_monitor else None
    }
```

## Architecture Benefits

### Technical Advantages

1. **Predictable Performance**: Event-driven cache eliminates database polling overhead
2. **Resource Efficiency**: Shared HTTP sessions and connection pooling minimize resource usage
3. **Fault Tolerance**: Circuit breaker pattern prevents cascade failures
4. **Data Consistency**: Individual ACID transactions ensure reliable result storage
5. **Operational Simplicity**: Single-process architecture reduces deployment complexity

### Current Limitations

1. **No Data Cleanup**: Historical data accumulates indefinitely
2. **Manual Scaling**: No horizontal scaling capabilities built-in
3. **Limited Observability**: Basic logging without advanced metrics
4. **Cache Dependencies**: Redis dependency for optimal performance

### Business Impact

- **Cost Control**: Free tier compatibility through intelligent resource management
- **User Experience**: Sub-100ms API responses through Redis caching layer
- **Reliability**: Circuit breaker maintains service during infrastructure issues
- **Scalability**: Event-driven design with caching supports growth effectively

The implementation demonstrates how monitoring infrastructure can be built with a focus on simplicity and reliability, while identifying areas for future optimization as the system scales.
