# app/services/dashboard_stats_service.py

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

from app.db.supabase import get_supabase
from app.schemas.dashboard_stats import (
    DashboardStatsResponse, 
    UptimeTrendPoint, 
    ResponseTimePoint, 
    IncidentSummary, 
    EndpointPerformance,
    PerformanceStats
)


class DashboardStatsService:
    """
    Comprehensive dashboard analytics service that aggregates all chart data
    in a single API call to minimize database queries and frontend complexity.
    """
    
    def __init__(self):
        self.supabase = get_supabase()
    
    async def get_dashboard_stats(self, user_id: str) -> DashboardStatsResponse:
        """
        Get comprehensive dashboard statistics for charts and metrics.
        
        Returns:
        - Uptime trend analysis (7 days)
        - Past 24 hours hourly response time
        - Recent incidents
        - Best/worst performing endpoints (24h)
        """
        try:
            # Get user's endpoint IDs first
            endpoint_ids = await self._get_user_endpoint_ids(user_id)
            
            if not endpoint_ids:
                return self._empty_stats_response()
            
            # Run all analytics queries in parallel for performance
            uptime_trend = await self._get_uptime_trend(endpoint_ids)
            response_time_trend = await self._get_response_time_trend(endpoint_ids)
            recent_incidents = await self._get_recent_incidents(user_id, endpoint_ids)
            endpoint_performance = await self._get_endpoint_performance(user_id, endpoint_ids)
            
            return DashboardStatsResponse(
                uptimeTrend=uptime_trend,
                responseTimeTrend=response_time_trend,
                recentIncidents=recent_incidents,
                endpointPerformance=endpoint_performance,
                generatedAt=datetime.now(),
                dataAvailable=len(endpoint_ids) > 0
            )
            
        except Exception as e:
            print(f"❌ Dashboard stats error: {e}")
            return self._empty_stats_response()
    
    async def _get_user_endpoint_ids(self, user_id: str) -> List[str]:
        """Get all endpoint IDs for a user across all workspaces."""
        try:
            # Get workspace IDs
            workspaces_response = self.supabase.table("workspaces").select("id").eq("user_id", user_id).execute()
            workspace_ids = [ws["id"] for ws in workspaces_response.data]
            
            if not workspace_ids:
                return []
            
            # Get endpoint IDs
            endpoints_response = self.supabase.table("endpoints").select("id").in_("workspace_id", workspace_ids).eq("is_active", True).execute()
            return [ep["id"] for ep in endpoints_response.data]
            
        except Exception as e:
            print(f"❌ Error getting user endpoints: {e}")
            return []
    
    async def _get_uptime_trend(self, endpoint_ids: List[str]) -> List[UptimeTrendPoint]:
        """
        Get 7-day uptime trend analysis.
        Available after 7 days of monitoring data.
        """
        try:
            if not endpoint_ids:
                return []
            
            seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
            
            # Get all check results for the past 7 days
            results_response = self.supabase.table("check_results").select(
                "checked_at, success, endpoint_id"
            ).in_(
                "endpoint_id", endpoint_ids
            ).gte(
                "checked_at", seven_days_ago
            ).order("checked_at", desc=False).execute()
            
            # Group by date and calculate daily uptime
            daily_data = defaultdict(lambda: {"total": 0, "successful": 0})
            
            for result in results_response.data:
                check_date = result["checked_at"][:10]  # YYYY-MM-DD
                daily_data[check_date]["total"] += 1
                if result["success"]:
                    daily_data[check_date]["successful"] += 1
            
            # Calculate uptime percentage for each day
            uptime_trend = []
            for date_str in sorted(daily_data.keys()):
                data = daily_data[date_str]
                uptime_percent = (data["successful"] / data["total"]) * 100 if data["total"] > 0 else 0
                
                uptime_trend.append(UptimeTrendPoint(
                    date=date_str,
                    uptime=round(uptime_percent, 2),
                    totalChecks=data["total"],
                    successfulChecks=data["successful"]
                ))
            
            # Only return if we have at least 7 days of data
            if len(uptime_trend) >= 7:
                return uptime_trend[-7:]  # Last 7 days
            else:
                return []  # Not enough data yet
                
        except Exception as e:
            print(f"❌ Uptime trend error: {e}")
            return []
    
    async def _get_response_time_trend(self, endpoint_ids: List[str]) -> List[ResponseTimePoint]:
        """
        Get past 24 hours hourly average response time.
        """
        try:
            if not endpoint_ids:
                return []
            
            twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).isoformat()
            
            # Get successful checks from last 24 hours
            results_response = self.supabase.table("check_results").select(
                "checked_at, response_time_ms"
            ).in_(
                "endpoint_id", endpoint_ids
            ).gte(
                "checked_at", twenty_four_hours_ago
            ).eq(
                "success", True
            ).order("checked_at", desc=False).execute()
            
            # Group by hour and calculate average response time
            hourly_data = defaultdict(list)
            
            for result in results_response.data:
                timestamp = datetime.fromisoformat(result["checked_at"].replace('Z', '+00:00'))
                hour_key = timestamp.replace(minute=0, second=0, microsecond=0)
                hourly_data[hour_key].append(result["response_time_ms"])
            
            # Calculate stats for each hour
            response_time_trend = []
            for hour_timestamp in sorted(hourly_data.keys()):
                response_times = hourly_data[hour_timestamp]
                
                response_time_trend.append(ResponseTimePoint(
                    timestamp=hour_timestamp.isoformat(),
                    avgResponseTime=round(statistics.mean(response_times)),
                    minResponseTime=min(response_times),
                    maxResponseTime=max(response_times),
                    sampleCount=len(response_times)
                ))
            
            return response_time_trend
            
        except Exception as e:
            print(f"❌ Response time trend error: {e}")
            return []
    
    async def _get_recent_incidents(self, user_id: str, endpoint_ids: List[str]) -> List[IncidentSummary]:
        """
        Get recent incidents from endpoint failures.
        An incident is defined as 3+ consecutive failures.
        """
        try:
            if not endpoint_ids:
                return []
            
            # Get endpoint names and workspace info
            endpoint_info = await self._get_endpoint_info(user_id)
            
            # Get recent check results (last 7 days)
            seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
            
            results_response = self.supabase.table("check_results").select(
                "checked_at, success, status_code, error_message, endpoint_id"
            ).in_(
                "endpoint_id", endpoint_ids
            ).gte(
                "checked_at", seven_days_ago
            ).order("checked_at", desc=False).execute()
            
            # Group by endpoint and find incident patterns
            endpoint_results = defaultdict(list)
            for result in results_response.data:
                endpoint_results[result["endpoint_id"]].append(result)
            
            incidents = []
            
            for endpoint_id, results in endpoint_results.items():
                endpoint_data = endpoint_info.get(endpoint_id)
                if not endpoint_data:
                    continue
                
                # Find consecutive failure sequences
                consecutive_failures = []
                current_failure_streak = []
                
                for result in results:
                    if not result["success"]:
                        current_failure_streak.append(result)
                    else:
                        if len(current_failure_streak) >= 3:  # Incident threshold
                            consecutive_failures.append(current_failure_streak)
                        current_failure_streak = []
                
                # Check if current streak is an ongoing incident
                if len(current_failure_streak) >= 3:
                    consecutive_failures.append(current_failure_streak)
                
                # Convert failure streaks to incidents
                for failure_streak in consecutive_failures:
                    start_time = failure_streak[0]["checked_at"]
                    end_time = failure_streak[-1]["checked_at"]
                    
                    # Check if incident is ongoing
                    is_ongoing = failure_streak == current_failure_streak
                    
                    # Calculate duration
                    start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                    duration_seconds = int((end_dt - start_dt).total_seconds())
                    
                    # Get primary error info
                    error_codes = [r["status_code"] for r in failure_streak if r["status_code"]]
                    primary_error_code = max(set(error_codes), key=error_codes.count) if error_codes else 0
                    
                    error_messages = [r["error_message"] for r in failure_streak if r["error_message"]]
                    primary_error = error_messages[0] if error_messages else "Unknown error"
                    
                    incidents.append(IncidentSummary(
                        endpointId=endpoint_id,
                        endpointName=endpoint_data["name"],
                        workspaceName=endpoint_data["workspace_name"],
                        status="ongoing" if is_ongoing else "resolved",
                        cause=primary_error,
                        durationSeconds=duration_seconds,
                        responseCode=primary_error_code,
                        startTime=start_time,
                        endTime=None if is_ongoing else end_time,
                        failureCount=len(failure_streak)
                    ))
            
            # Sort by start time (most recent first) and limit to 10
            incidents.sort(key=lambda x: x.startTime, reverse=True)
            return incidents[:10]
            
        except Exception as e:
            print(f"❌ Recent incidents error: {e}")
            return []
    
    async def _get_endpoint_performance(self, user_id: str, endpoint_ids: List[str]) -> PerformanceStats:
        """Get best and worst performing endpoints in the past 24 hours."""
        try:
            if not endpoint_ids:
                return PerformanceStats(bestPerforming=[], worstPerforming=[])
            
            endpoint_info = await self._get_endpoint_info(user_id)
            
            twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).isoformat()
            
            results_response = self.supabase.table("check_results").select(
                "success, response_time_ms, endpoint_id"
            ).in_(
                "endpoint_id", endpoint_ids
            ).gte(
                "checked_at", twenty_four_hours_ago
            ).execute()

            if not results_response.data:
                return PerformanceStats(bestPerforming=[], worstPerforming=[])
            
            endpoint_metrics = defaultdict(lambda: {
                "total_checks": 0,
                "successful_checks": 0,
                "response_times": []
            })
            
            for result in results_response.data:
                endpoint_id = result["endpoint_id"]
                metrics = endpoint_metrics[endpoint_id]
                
                metrics["total_checks"] += 1
                if result["success"]:
                    metrics["successful_checks"] += 1
                    response_time = result.get("response_time_ms")
                    if response_time is not None:
                        try:
                            response_time_val = float(response_time)
                            if response_time_val > 0:
                                metrics["response_times"].append(response_time_val)
                        except (ValueError, TypeError):
                            pass
            
            performance_list = []
            
            for endpoint_id, metrics in endpoint_metrics.items():
                endpoint_data = endpoint_info.get(endpoint_id)
                if not endpoint_data or metrics["total_checks"] == 0:
                    continue
                
                try:
                    uptime = (metrics["successful_checks"] / metrics["total_checks"]) * 100
                    uptime = max(0.0, min(100.0, uptime))
                except ZeroDivisionError:
                    uptime = 0.0
                
                avg_response_time = 0.0
                if metrics["response_times"]:
                    try:
                        avg_response_time = statistics.mean(metrics["response_times"])
                        if avg_response_time < 0:
                            avg_response_time = 0.0
                    except (statistics.StatisticsError, TypeError):
                        avg_response_time = 0.0
                
                performance_score = uptime - (avg_response_time / 100)
                
                performance_list.append(EndpointPerformance(
                    endpointId=endpoint_id,
                    endpointName=endpoint_data["name"],
                    workspaceName=endpoint_data["workspace_name"],
                    uptime=round(uptime, 2),
                    avgResponseTime=round(avg_response_time) if avg_response_time else None,
                    totalChecks=metrics["total_checks"],
                    performanceScore=round(performance_score, 2)
                ))
            
            performance_list.sort(key=lambda x: x.performanceScore, reverse=True)
            
            qualified_endpoints = [ep for ep in performance_list if ep.totalChecks >= 3]
            
            best_performing = qualified_endpoints[:5]
            worst_performing = qualified_endpoints[-5:] if len(qualified_endpoints) > 5 else []
            worst_performing.reverse()
            
            return PerformanceStats(
                bestPerforming=best_performing,
                worstPerforming=worst_performing
            )
            
        except Exception as e:
            print(f"❌ Endpoint performance calculation error: {e}")
            return PerformanceStats(bestPerforming=[], worstPerforming=[])
    
    async def _get_endpoint_info(self, user_id: str) -> Dict[str, Dict[str, str]]:
        """Get endpoint names and workspace info for a user."""
        try:
            # Get workspaces with endpoint info
            workspaces_response = self.supabase.table("workspaces").select("""
                id, name,
                endpoints(id, name, is_active)
            """).eq("user_id", user_id).execute()
            
            endpoint_info = {}
            for workspace in workspaces_response.data:
                workspace_name = workspace["name"]
                for endpoint in workspace.get("endpoints", []):
                    endpoint_info[endpoint["id"]] = {
                        "name": endpoint["name"],
                        "workspace_name": workspace_name
                    }
            
            return endpoint_info
            
        except Exception as e:
            print(f"❌ Error getting endpoint info: {e}")
            return {}
    
    def _empty_stats_response(self) -> DashboardStatsResponse:
        """Return empty stats response when no data is available."""
        return DashboardStatsResponse(
            uptimeTrend=[],
            responseTimeTrend=[],
            recentIncidents=[],
            endpointPerformance=PerformanceStats(bestPerforming=[], worstPerforming=[]),
            generatedAt=datetime.now(),
            dataAvailable=False
        )