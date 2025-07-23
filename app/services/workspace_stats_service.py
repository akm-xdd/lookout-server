# app/services/workspace_stats_service.py

from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from fastapi import HTTPException, status
from uuid import UUID
from collections import defaultdict

from app.db.supabase import get_supabase_admin
from app.schemas.workspace_stats import (
    WorkspaceStatsResponse, 
    WorkspaceStatsEndpoint,
    WorkspaceStatsOverview,
    WorkspaceStatsHealth
)


class WorkspaceStatsService:
    """
    Unified service for calculating comprehensive workspace statistics.
    Handles inactive endpoints, 24-hour data windows, and accurate metrics.
    """
    
    def __init__(self):
        self.supabase = get_supabase_admin()

    async def get_workspace_stats(self, workspace_id: UUID, user_id: str) -> WorkspaceStatsResponse:
        """
        Get comprehensive workspace statistics in a single call.
        
        Includes:
        - Workspace basic info
        - All endpoints with 24h monitoring data
        - Calculated metrics (only from active endpoints)
        - Health summary
        - Status determination
        
        Args:
            workspace_id: Workspace UUID
            user_id: User ID for authorization
            
        Returns:
            Complete workspace statistics
        """
        try:
            # 1. Validate workspace exists and belongs to user
            workspace_data = await self._get_workspace_info(workspace_id, user_id)
            
            # 2. Get all endpoints for this workspace
            endpoints_data = await self._get_workspace_endpoints(workspace_id)
            
            # 3. Get 24h monitoring stats for all endpoints
            monitoring_stats = await self._get_24h_monitoring_stats(endpoints_data)
            
            # 4. Calculate workspace-level metrics (active endpoints only)
            overview = await self._calculate_workspace_overview(endpoints_data, monitoring_stats)
            
            # 5. Get recent incidents (both ongoing and recently resolved)
            recent_incidents = await self._get_recent_incidents(endpoints_data, monitoring_stats)
            
            # 6. Calculate health metrics
            health = await self._calculate_health_metrics(endpoints_data, monitoring_stats, recent_incidents)
            
            # 7. Build endpoint responses with monitoring data
            endpoints = await self._build_endpoint_responses(endpoints_data, monitoring_stats)
            
            return WorkspaceStatsResponse(
                workspace=workspace_data,
                endpoints=endpoints,
                overview=overview,
                health=health,
                recent_incidents=recent_incidents,  # ADD THIS
                generated_at=datetime.now(),
                data_window_hours=24
            )
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get workspace stats: {str(e)}"
            )

    async def _get_workspace_info(self, workspace_id: UUID, user_id: str) -> Dict[str, Any]:
        """Get and validate workspace basic information."""
        try:
            response = self.supabase.table("workspaces").select("*").eq(
                "id", str(workspace_id)
            ).eq("user_id", user_id).execute()
            
            if not response.data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Workspace not found"
                )
            
            return response.data[0]
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get workspace info: {str(e)}"
            )

    async def _get_workspace_endpoints(self, workspace_id: UUID) -> List[Dict[str, Any]]:
        """Get all endpoints for the workspace."""
        try:
            response = self.supabase.table("endpoints").select("*").eq(
                "workspace_id", str(workspace_id)
            ).execute()
            
            return response.data or []
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get workspace endpoints: {str(e)}"
            )

    async def _get_24h_monitoring_stats(self, endpoints_data: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Get 24-hour monitoring statistics for all endpoints.
        Returns dict keyed by endpoint_id.
        """
        if not endpoints_data:
            return {}
            
        try:
            endpoint_ids = [ep['id'] for ep in endpoints_data]
            
            # Get stats from the endpoint_stats view (which already calculates 24h metrics)
            stats_response = self.supabase.table("endpoint_stats").select("*").in_(
                "id", endpoint_ids
            ).execute()
            
            # Convert to dict keyed by endpoint_id
            stats_dict = {}
            for stat in stats_response.data:
                # Ensure numeric fields are properly typed
                processed_stat = self._process_monitoring_stat(stat)
                stats_dict[stat['id']] = processed_stat
            
            return stats_dict
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get monitoring stats: {str(e)}"
            )

    def _process_monitoring_stat(self, stat: Dict[str, Any]) -> Dict[str, Any]:
        """Process and clean monitoring statistic data."""
        processed = dict(stat)
        
        # Convert string numbers to proper types
        if processed.get('avg_response_time_24h'):
            try:
                processed['avg_response_time_24h'] = float(processed['avg_response_time_24h'])
            except (ValueError, TypeError):
                processed['avg_response_time_24h'] = None
        
        # Ensure integer fields
        processed['checks_last_24h'] = processed.get('checks_last_24h') or 0
        processed['successful_checks_24h'] = processed.get('successful_checks_24h') or 0
        processed['consecutive_failures'] = processed.get('consecutive_failures') or 0
        
        # Ensure boolean and numeric fields
        processed['last_response_time'] = processed.get('last_response_time')
        processed['last_status_code'] = processed.get('last_status_code')
        
        return processed

    async def _calculate_workspace_overview(
        self, 
        endpoints_data: List[Dict[str, Any]], 
        monitoring_stats: Dict[str, Dict[str, Any]]
    ) -> WorkspaceStatsOverview:
        """
        Calculate workspace-level overview metrics.
        ONLY includes active endpoints in calculations.
        """
        total_endpoints = len(endpoints_data)
        active_endpoints = sum(1 for ep in endpoints_data if ep.get('is_active', True))
        
        if active_endpoints == 0:
            return WorkspaceStatsOverview(
                total_endpoints=total_endpoints,
                active_endpoints=0,
                online_endpoints=0,
                warning_endpoints=0,
                offline_endpoints=0,
                unknown_endpoints=0,
                avg_uptime_24h=None,
                avg_response_time_24h=None,
                total_checks_24h=0,
                successful_checks_24h=0,
                last_check_at=None
            )
        
        # Process only active endpoints
        online_count = 0
        warning_count = 0
        offline_count = 0
        unknown_count = 0
        
        response_times = []
        uptime_percentages = []
        total_checks = 0
        successful_checks = 0
        latest_check = None
        
        for endpoint in endpoints_data:
            # Skip inactive endpoints from all calculations
            if not endpoint.get('is_active', True):
                continue
                
            endpoint_id = endpoint['id']
            stat = monitoring_stats.get(endpoint_id, {})
            
            # Determine endpoint status
            status = self._determine_endpoint_status(endpoint, stat)
            if status == 'online':
                online_count += 1
            elif status == 'warning':
                warning_count += 1
            elif status == 'offline':
                offline_count += 1
            else:
                unknown_count += 1
            
            # Aggregate response times (24h average)
            avg_response_time = stat.get('avg_response_time_24h')
            if avg_response_time is not None:
                try:
                    response_time_val = float(avg_response_time)
                    if response_time_val > 0:
                        response_times.append(response_time_val)
                except (ValueError, TypeError):
                    pass
            
            # Aggregate uptime data
            checks_24h = stat.get('checks_last_24h', 0)
            successful_24h = stat.get('successful_checks_24h', 0)
            
            if checks_24h > 0 and successful_24h >= 0:
                uptime_percent = (successful_24h / checks_24h) * 100
                uptime_percentages.append(uptime_percent)
                total_checks += checks_24h
                successful_checks += successful_24h
            
            # Track latest check time
            last_check = stat.get('last_check_at')
            if last_check:
                try:
                    if isinstance(last_check, str):
                        from datetime import datetime
                        parsed_check = datetime.fromisoformat(last_check.replace('Z', '+00:00'))
                        if not latest_check or parsed_check > latest_check:
                            latest_check = parsed_check
                    elif hasattr(last_check, 'year'):
                        if not latest_check or last_check > latest_check:
                            latest_check = last_check
                except (ValueError, TypeError, AttributeError):
                    pass
        
        # Calculate averages
        avg_response_time = None
        if response_times:
            try:
                avg_response_time = sum(response_times) / len(response_times)
                if avg_response_time < 0:
                    avg_response_time = None
            except (ZeroDivisionError, TypeError):
                avg_response_time = None

        avg_uptime = None
        if uptime_percentages:
            try:
                avg_uptime = sum(uptime_percentages) / len(uptime_percentages)
                if avg_uptime < 0:
                    avg_uptime = 0.0
                elif avg_uptime > 100:
                    avg_uptime = 100.0
            except (ZeroDivisionError, TypeError):
                avg_uptime = None

        
        avg_uptime = (
            sum(uptime_percentages) / len(uptime_percentages) 
            if uptime_percentages else None
        )
        
        return WorkspaceStatsOverview(
            total_endpoints=total_endpoints,
            active_endpoints=active_endpoints,
            online_endpoints=online_count,
            warning_endpoints=warning_count,
            offline_endpoints=offline_count,
            unknown_endpoints=unknown_count,
            avg_uptime_24h=round(avg_uptime, 2) if avg_uptime is not None else None,
            avg_response_time_24h=round(avg_response_time, 2) if avg_response_time is not None else None,
            total_checks_24h=total_checks,
            successful_checks_24h=successful_checks,
            last_check_at=latest_check
        )

    async def _get_recent_incidents(
        self, 
        endpoints_data: List[Dict[str, Any]], 
        monitoring_stats: Dict[str, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Get recent incidents (ongoing and recently resolved).
        An incident is 3+ consecutive failures.
        """
        if not endpoints_data:
            return []
            
        try:
            # Get recent check results for analysis
            endpoint_ids = [ep['id'] for ep in endpoints_data]
            twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).isoformat()
            
            # Get check results from last 24 hours
            results_response = self.supabase.table("check_results").select(
                "endpoint_id, checked_at, success, status_code, error_message"
            ).in_(
                "endpoint_id", endpoint_ids
            ).gte(
                "checked_at", twenty_four_hours_ago
            ).order("checked_at", desc=False).execute()
            
            # Group by endpoint and analyze for incidents
            endpoint_results = defaultdict(list)
            for result in results_response.data:
                endpoint_results[result['endpoint_id']].append(result)
            
            incidents = []
            
            for endpoint in endpoints_data:
                if not endpoint.get('is_active', True):
                    continue
                    
                endpoint_id = endpoint['id']
                results = endpoint_results.get(endpoint_id, [])
                stat = monitoring_stats.get(endpoint_id, {})
                
                if not results:
                    continue
                
                # Find consecutive failure streaks of 3+
                current_streak = []
                failure_streaks = []
                
                for result in results:
                    if not result['success']:
                        current_streak.append(result)
                    else:
                        if len(current_streak) >= 3:
                            failure_streaks.append(current_streak)
                        current_streak = []
                
                # Check if current streak is ongoing
                if len(current_streak) >= 3:
                    failure_streaks.append(current_streak)
                
                # Convert streaks to incidents
                for streak in failure_streaks:
                    start_time = streak[0]['checked_at']
                    end_time = streak[-1]['checked_at']
                    
                    # Determine if ongoing (current streak)
                    is_ongoing = (
                        streak == current_streak and 
                        stat.get('last_check_success') is False
                    )
                    
                    # Calculate duration
                    start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                    duration_minutes = int((end_dt - start_dt).total_seconds() / 60)
                    
                    # Get primary error info
                    error_codes = [r['status_code'] for r in streak if r.get('status_code')]
                    primary_error_code = max(set(error_codes), key=error_codes.count) if error_codes else 0
                    
                    error_messages = [r['error_message'] for r in streak if r.get('error_message')]
                    primary_error = error_messages[0] if error_messages else "Connection failed"
                    
                    incidents.append({
                        'endpoint_id': endpoint_id,
                        'endpoint_name': endpoint['name'],
                        'status': 'ongoing' if is_ongoing else 'resolved',
                        'cause': primary_error,
                        'duration_minutes': duration_minutes,
                        'failure_count': len(streak),
                        'status_code': primary_error_code,
                        'start_time': start_time,
                        'end_time': None if is_ongoing else end_time,
                        'detected_at': start_time
                    })
            
            # Sort by start time (most recent first) and limit
            incidents.sort(key=lambda x: x['start_time'], reverse=True)
            return incidents[:10]  # Return last 10 incidents
            
        except Exception as e:
            print(f"❌ Error getting recent incidents: {e}")
            return []

    async def _calculate_health_metrics(
        self, 
        endpoints_data: List[Dict[str, Any]], 
        monitoring_stats: Dict[str, Dict[str, Any]],
        recent_incidents: List[Dict[str, Any]]
    ) -> WorkspaceStatsHealth:
        """Calculate workspace health metrics."""
        active_endpoints = [ep for ep in endpoints_data if ep.get('is_active', True)]
        
        if not active_endpoints:
            return WorkspaceStatsHealth(
                status='unknown',
                health_score=None,
                active_incidents=0,
                last_incident_at=None,
                uptime_trend_7d=[],  # Could be populated later if needed
                response_time_trend_24h=[]  # Could be populated later if needed
            )
        
        # Count incidents (from the incidents we just calculated)
        active_incidents = len([inc for inc in recent_incidents if inc['status'] == 'ongoing'])
        last_incident = None
        
        if recent_incidents:
            # Get the most recent incident start time
            last_incident = recent_incidents[0]['start_time']
        
        online_count = 0
        
        for endpoint in active_endpoints:
            endpoint_id = endpoint['id']
            stat = monitoring_stats.get(endpoint_id, {})
            
            # Count online endpoints for health score
            if self._determine_endpoint_status(endpoint, stat) == 'online':
                online_count += 1
        
        # Calculate health score (percentage of online active endpoints)
        health_score = round((online_count / len(active_endpoints)) * 100, 1)
        
        # NEW: Calculate Performance Weather
        weather_data = self._calculate_performance_weather(
            health_score, active_incidents, len(active_endpoints)
        )
        
        # Determine overall status
        if active_incidents > 0:
            if health_score < 50:
                status = 'critical'
            elif health_score < 80:
                status = 'degraded'
            else:
                status = 'warning'
        elif health_score >= 95:
            status = 'operational'
        elif health_score >= 80:
            status = 'warning'
        else:
            status = 'degraded'
        
        return WorkspaceStatsHealth(
            status=status,
            health_score=health_score,
            active_incidents=active_incidents,
            last_incident_at=last_incident,
            weather=weather_data["weather"],
            weather_emoji=weather_data["emoji"],
            weather_description=weather_data["description"],
            uptime_trend_7d=[],  # Placeholder for future implementation
            response_time_trend_24h=[]  # Placeholder for future implementation
        )

    def _determine_endpoint_status(self, endpoint: Dict[str, Any], stat: Dict[str, Any]) -> str:
        """
        Determine the status of an endpoint based on its configuration and monitoring data.
        
        Rules:
        - inactive endpoints are not considered (caller filters these out)
        - online: last check succeeded
        - warning: last check failed but < 3 consecutive failures
        - offline: 3+ consecutive failures
        - unknown: no monitoring data or never checked
        """
        if not endpoint.get('is_active', True):
            return 'inactive'  # This shouldn't be called for inactive endpoints
        
        last_check_success = stat.get('last_check_success')
        consecutive_failures = stat.get('consecutive_failures', 0)
        
        if last_check_success is True:
            return 'online'
        elif last_check_success is False:
            if consecutive_failures >= 3:
                return 'offline'
            else:
                return 'warning'
        else:
            return 'unknown'

    async def _build_endpoint_responses(
        self, 
        endpoints_data: List[Dict[str, Any]], 
        monitoring_stats: Dict[str, Dict[str, Any]]
    ) -> List[WorkspaceStatsEndpoint]:
        """Build endpoint response objects with monitoring data."""
        endpoint_responses = []
        
        for endpoint in endpoints_data:
            endpoint_id = endpoint['id']
            stat = monitoring_stats.get(endpoint_id, {})
            
            # Calculate uptime percentage for this endpoint
            checks_24h = stat.get('checks_last_24h', 0)
            successful_24h = stat.get('successful_checks_24h', 0)
            uptime_24h = (
                (successful_24h / checks_24h) * 100 
                if checks_24h > 0 else None
            )
            
            endpoint_response = WorkspaceStatsEndpoint(
                id=endpoint_id,
                name=endpoint['name'],
                url=endpoint['url'],
                method=endpoint.get('method', 'GET'),
                is_active=endpoint.get('is_active', True),
                frequency_minutes=endpoint.get('frequency_minutes', 5),
                timeout_seconds=endpoint.get('timeout_seconds', 30),
                expected_status=endpoint.get('expected_status', 200),
                created_at=endpoint['created_at'],
                
                # Monitoring data (24h window)
                status=self._determine_endpoint_status(endpoint, stat),
                uptime_24h=round(uptime_24h, 2) if uptime_24h is not None else None,
                avg_response_time_24h=stat.get('avg_response_time_24h'),
                checks_last_24h=checks_24h,
                successful_checks_24h=successful_24h,
                consecutive_failures=stat.get('consecutive_failures', 0),
                
                # Latest check data
                last_check_at=stat.get('last_check_at'),
                last_check_success=stat.get('last_check_success'),
                last_response_time=stat.get('last_response_time'),
                last_status_code=stat.get('last_status_code'),
                last_error_message=stat.get('last_error_message')
            )
            
            endpoint_responses.append(endpoint_response)
        
        # Sort by name for consistent ordering
        endpoint_responses.sort(key=lambda x: x.name.lower())
        
        return endpoint_responses

    def _calculate_performance_weather(
        self, 
        health_score: Optional[float], 
        active_incidents: int, 
        total_active_endpoints: int
    ) -> Dict[str, str]:
        """
        Calculate performance weather based on health metrics.
        
        Weather Logic:
        ☀️ Sunny: 95%+ health, no incidents
        ⛅ Partly Cloudy: 80-94% health, minor issues
        ☁️ Cloudy: 60-79% health, multiple issues
        ⛈️ Stormy: <60% health or multiple active incidents
        ❓ Unknown: No data or no active endpoints
        """
        if health_score is None or total_active_endpoints == 0:
            return {
                "weather": "unknown",
                "emoji": "❓",
                "description": "No monitoring data available"
            }
        
        # Determine weather based on health score and incidents
        if health_score >= 95 and active_incidents == 0:
            return {
                "weather": "sunny",
                "emoji": "☀️",
                "description": "All systems running smoothly"
            }
        elif health_score >= 80 and active_incidents <= 1:
            incident_text = f" with {active_incidents} minor issue" if active_incidents == 1 else ""
            return {
                "weather": "partly_cloudy", 
                "emoji": "⛅",
                "description": f"Mostly stable{incident_text}"
            }
        elif health_score >= 60 and active_incidents <= 2:
            if active_incidents > 0:
                return {
                    "weather": "cloudy",
                    "emoji": "☁️", 
                    "description": f"Some issues detected - {active_incidents} endpoint{'s' if active_incidents != 1 else ''} affected"
                }
            else:
                return {
                    "weather": "cloudy",
                    "emoji": "☁️", 
                    "description": "Performance below optimal levels"
                }
        else:
            if active_incidents >= 3:
                return {
                    "weather": "stormy",
                    "emoji": "⛈️",
                    "description": f"Major disruptions - {active_incidents} active incidents"
                }
            else:
                return {
                    "weather": "stormy", 
                    "emoji": "⛈️",
                    "description": f"Significant performance issues ({health_score:.1f}% health)"
                }