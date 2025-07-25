from fastapi import HTTPException, status, Depends
from typing import List, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict

from app.db.supabase import get_supabase
from app.schemas.dashboard import (
    DashboardResponse, DashboardUserStats, DashboardUserLimits, DashboardUserCurrent,
    DashboardWorkspace, DashboardOverview, DashboardIncident
)
from app.schemas.endpoint import EndpointResponse
from app.core.constants import MAX_WORKSPACES_PER_USER, MAX_TOTAL_ENDPOINTS_PER_USER
from app.core.cache import redis_cache

class DashboardService:
    def __init__(self, supabase=Depends(get_supabase)):
        self.supabase = supabase

    @redis_cache(ttl=60, key_prefix="dashboard")
    async def get_dashboard_data(self, user_id: str, user_email: str) -> DashboardResponse:
        try:
            workspaces_response = self.supabase.table("workspaces").select("""
                *,
                endpoints(
                    id, name, url, method, headers, body, expected_status,
                    frequency_minutes, timeout_seconds, is_active, created_at, workspace_id
                )
            """).eq("user_id", user_id).order("created_at", desc=False).execute()
            
            workspaces_data = workspaces_response.data or []

            all_endpoint_ids = []
            for workspace in workspaces_data:
                for endpoint in workspace.get('endpoints', []):
                    all_endpoint_ids.append(endpoint['id'])

            if not all_endpoint_ids:
                return self._build_empty_dashboard(user_id, user_email, workspaces_data)

            endpoint_stats = await self._get_endpoint_stats(all_endpoint_ids)
            
            uptime_history = await self._get_uptime_trend(user_id)
            response_time_history = await self._get_response_time_history(user_id)
            recent_incidents = await self._get_recent_incidents(user_id)
            best_worst_endpoints = await self._get_best_worst_endpoints(user_id)

            dashboard_workspaces = []
            total_endpoints = 0
            active_endpoints = 0

            for workspace_raw in workspaces_data:
                endpoints_raw = workspace_raw.get('endpoints', [])
                endpoints = []
                workspace_endpoint_ids = []
                
                for endpoint_raw in endpoints_raw:
                    endpoint = EndpointResponse(**endpoint_raw)
                    endpoints.append(endpoint)
                    total_endpoints += 1
                    if endpoint_raw.get('is_active', True):
                        workspace_endpoint_ids.append(endpoint_raw['id'])
                        active_endpoints += 1

                workspace_status = "operational"
                workspace_uptime = 100.0
                workspace_avg_response = 0
                workspace_last_check = None
                workspace_active_incidents = 0
                
                if workspace_endpoint_ids:
                    total_response_time = 0
                    valid_response_times = 0
                    uptime_values = []
                    latest_check = None
                    workspace_true_incidents = 0
                    
                    for endpoint_id in workspace_endpoint_ids:
                        if endpoint_id in endpoint_stats:
                            stat = endpoint_stats[endpoint_id]
                            
                            avg_response = stat.get('avg_response_time_24h')
                            if avg_response and avg_response > 0:
                                total_response_time += avg_response
                                valid_response_times += 1
                            
                            checks_24h = stat.get('checks_last_24h', 0)
                            successful_24h = stat.get('successful_checks_24h', 0)
                            if checks_24h > 0:
                                endpoint_uptime = (successful_24h / checks_24h) * 100
                                uptime_values.append(endpoint_uptime)
                            
                            last_check = stat.get('last_check_at')
                            if last_check and (not latest_check or last_check > latest_check):
                                latest_check = last_check
                            
                            consecutive_failures = stat.get('consecutive_failures', 0)
                            last_check_failed = not stat.get('last_check_success', True)
                            
                            if consecutive_failures >= 3:
                                workspace_true_incidents += 1
                            elif consecutive_failures > 0 and last_check_failed:
                                workspace_active_incidents += 1
                    
                    if valid_response_times > 0:
                        workspace_avg_response = total_response_time / valid_response_times
                    workspace_uptime = sum(uptime_values) / len(uptime_values) if uptime_values else 100.0
                    workspace_last_check = latest_check
                    
                    if workspace_true_incidents > 0:
                        workspace_status = "degraded" if workspace_uptime > 90 else "down"
                    elif workspace_active_incidents > 0:
                        workspace_status = "warning" if workspace_uptime > 95 else "degraded"
                    
                    workspace_active_incidents += workspace_true_incidents

                dashboard_workspace = DashboardWorkspace(
                    id=workspace_raw['id'],
                    name=workspace_raw['name'],
                    description=workspace_raw.get('description'),
                    created_at=workspace_raw['created_at'],
                    updated_at=workspace_raw['updated_at'],
                    user_id=workspace_raw['user_id'],
                    endpoint_count=len(endpoints),
                    endpoints=endpoints,
                    status=workspace_status,
                    uptime=workspace_uptime,
                    avg_response_time=workspace_avg_response,
                    last_check=workspace_last_check,
                    active_incidents=workspace_active_incidents
                )
                dashboard_workspaces.append(dashboard_workspace)

            user_stats = DashboardUserStats(
                id=user_id,
                email=user_email,
                limits=DashboardUserLimits(
                    max_workspaces=MAX_WORKSPACES_PER_USER,
                    max_total_endpoints=MAX_TOTAL_ENDPOINTS_PER_USER
                ),
                current=DashboardUserCurrent(
                    workspace_count=len(dashboard_workspaces),
                    total_endpoints=total_endpoints
                )
            )

            overview = DashboardOverview(
                total_endpoints=total_endpoints,
                active_endpoints=active_endpoints,
                total_workspaces=len(dashboard_workspaces),
                uptimeHistory=uptime_history,
                responseTimeHistory=response_time_history,
                bestPerformingEndpoints=best_worst_endpoints['best'],
                worstPerformingEndpoints=best_worst_endpoints['worst']
            )

            return DashboardResponse(
                user=user_stats,
                workspaces=dashboard_workspaces,
                overview=overview,
                recentIncidents=recent_incidents
            )

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to load dashboard data: {str(e)}"
            )

    def _build_empty_dashboard(self, user_id: str, user_email: str, workspaces_data: List[Dict]) -> DashboardResponse:
        dashboard_workspaces = []
        for workspace_raw in workspaces_data:
            dashboard_workspace = DashboardWorkspace(
                id=workspace_raw['id'],
                name=workspace_raw['name'],
                description=workspace_raw.get('description'),
                created_at=workspace_raw['created_at'],
                updated_at=workspace_raw['updated_at'],
                user_id=workspace_raw['user_id'],
                endpoint_count=0,
                endpoints=[]
            )
            dashboard_workspaces.append(dashboard_workspace)

        user_stats = DashboardUserStats(
            id=user_id,
            email=user_email,
            limits=DashboardUserLimits(
                max_workspaces=MAX_WORKSPACES_PER_USER,
                max_total_endpoints=MAX_TOTAL_ENDPOINTS_PER_USER
            ),
            current=DashboardUserCurrent(
                workspace_count=len(dashboard_workspaces),
                total_endpoints=0
            )
        )

        overview = DashboardOverview(
            total_endpoints=0,
            active_endpoints=0,
            total_workspaces=len(dashboard_workspaces),
            uptimeHistory=[],
            responseTimeHistory=[],
            bestPerformingEndpoints=[],
            worstPerformingEndpoints=[]
        )

        return DashboardResponse(
            user=user_stats,
            workspaces=dashboard_workspaces,
            overview=overview,
            recentIncidents=[]
        )

    async def _get_endpoint_stats(self, endpoint_ids: List[str]) -> Dict[str, Dict]:
        try:
            stats_response = self.supabase.table("endpoint_stats").select("*").in_("id", endpoint_ids).execute()
            endpoint_stats = {}
            for stat in stats_response.data:
                if stat.get('avg_response_time_24h'):
                    try:
                        stat['avg_response_time_24h'] = float(stat['avg_response_time_24h'])
                    except (ValueError, TypeError):
                        stat['avg_response_time_24h'] = None
                endpoint_stats[stat['id']] = stat
            return endpoint_stats
        except Exception:
            return {}

    async def _get_uptime_trend(self, user_id: str) -> List[Dict[str, Any]]:
        try:
            endpoint_ids = await self._get_user_endpoint_ids(user_id)
            if not endpoint_ids:
                return []

            seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
            
            results_response = self.supabase.table("check_results").select(
                "checked_at, success"
            ).in_(
                "endpoint_id", endpoint_ids
            ).eq(
                "is_active", True
            ). gte(
                "checked_at", seven_days_ago
            ).execute()

            daily_data = defaultdict(list)
            for result in results_response.data:
                check_date = result["checked_at"][:10]
                daily_data[check_date].append(result["success"])

            uptime_history = []
            for date_str, successes in daily_data.items():
                uptime_percent = (sum(successes) / len(successes)) * 100
                uptime_history.append({
                    "date": date_str,
                    "uptime": round(uptime_percent, 2)
                })

            uptime_history.sort(key=lambda x: x["date"])
            return uptime_history

        except Exception:
            return []

    async def _get_response_time_history(self, user_id: str) -> List[Dict[str, Any]]:
        try:
            endpoint_ids = await self._get_user_endpoint_ids(user_id)
            if not endpoint_ids:
                return []

            twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).isoformat()

            results_response = self.supabase.table("check_results").select(
                "checked_at, response_time_ms"
            ).in_(
                "endpoint_id", endpoint_ids
            ).gte(
                "checked_at", twenty_four_hours_ago
            ).eq(
                "success", True
            ).execute()

            hourly_data = defaultdict(list)
            for result in results_response.data:
                timestamp = datetime.fromisoformat(result["checked_at"].replace('Z', '+00:00'))
                hour_key = timestamp.replace(minute=0, second=0, microsecond=0)
                hourly_data[hour_key].append(result["response_time_ms"])

            response_time_history = []
            for hour_timestamp, response_times in hourly_data.items():
                avg_response_time = sum(response_times) / len(response_times)
                response_time_history.append({
                    "timestamp": hour_timestamp.isoformat(),
                    "avgResponseTime": round(avg_response_time)
                })

            response_time_history.sort(key=lambda x: x["timestamp"])
            return response_time_history

        except Exception:
            return []

    async def _get_recent_incidents(self, user_id: str) -> List[DashboardIncident]:
        try:
            workspaces_response = self.supabase.table("workspaces").select(
                "id, name, endpoints(id, name, is_active)"
            ).eq("user_id", user_id).execute()
            
            all_incidents = []
            
            for workspace in workspaces_response.data:
                workspace_name = workspace['name']
                endpoints_data = workspace.get('endpoints', [])
                
                if not endpoints_data:
                    continue
                    
                endpoint_ids = [ep['id'] for ep in endpoints_data]
                twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).isoformat()
                
                results_response = self.supabase.table("check_results").select(
                    "endpoint_id, checked_at, success, status_code, error_message"
                ).in_(
                    "endpoint_id", endpoint_ids
                ).gte(
                    "checked_at", twenty_four_hours_ago
                ).order("checked_at", desc=False).execute()
                
                endpoint_results = defaultdict(list)
                for result in results_response.data:
                    endpoint_results[result['endpoint_id']].append(result)
                
                for endpoint in endpoints_data:
                    if not endpoint.get('is_active', True):
                        continue
                    endpoint_id = endpoint['id']
                    endpoint_name = endpoint['name']
                    results = endpoint_results.get(endpoint_id, [])
                    
                    if not results:
                        continue
                    
                    current_streak = []
                    failure_streaks = []
                    
                    for result in results:
                        if not result['success']:
                            current_streak.append(result)
                        else:
                            if len(current_streak) >= 3:
                                failure_streaks.append(current_streak)
                            current_streak = []
                    
                    if len(current_streak) >= 3:
                        failure_streaks.append(current_streak)
                    
                    for streak in failure_streaks:
                        start_time = streak[0]['checked_at']
                        end_time = streak[-1]['checked_at']
                        
                        is_ongoing = streak == current_streak
                        
                        start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                        end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                        duration_seconds = int((end_dt - start_dt).total_seconds())
                        
                        error_codes = [r['status_code'] for r in streak if r.get('status_code')]
                        primary_error_code = max(set(error_codes), key=error_codes.count) if error_codes else 0
                        
                        error_messages = [r['error_message'] for r in streak if r.get('error_message')]
                        primary_error = error_messages[0] if error_messages else "Connection failed"
                        
                        incident = DashboardIncident(
                            id=f"{endpoint_id}-{start_time}",
                            endpointName=endpoint_name,
                            workspaceName="",
                            status='ongoing' if is_ongoing else 'resolved',
                            cause=primary_error,
                            duration=duration_seconds,
                            responseCode=primary_error_code,
                            startTime=start_time,
                            endTime=None if is_ongoing else end_time
                        )
                        all_incidents.append(incident)
            
            all_incidents.sort(key=lambda x: x.startTime, reverse=True)
            return all_incidents[:10]
            
        except Exception as e:
            print(f"❌ Dashboard incidents error: {e}")
            return []

    async def _get_best_worst_endpoints(self, user_id: str) -> Dict[str, List[Dict[str, Any]]]:
        try:
            workspaces_response = self.supabase.table("workspaces").select(
                "name, endpoints(id, name, is_active)"
            ).eq("user_id", user_id).execute()

            endpoint_performance = []
            
            for workspace in workspaces_response.data:
                workspace_name = workspace['name']
                for endpoint in workspace.get('endpoints', []):
                    endpoint_id = endpoint['id']
                    endpoint_name = endpoint['name']
                    
                    stats_response = self.supabase.table("endpoint_stats").select(
                        "avg_response_time_24h, successful_checks_24h, checks_last_24h"
                    ).eq("id", endpoint_id).execute()
                    
                    if stats_response.data:
                        stat = stats_response.data[0]
                        avg_response = stat.get('avg_response_time_24h')
                        successful_checks = stat.get('successful_checks_24h', 0)
                        total_checks = stat.get('checks_last_24h', 0)
                        
                        if total_checks > 0 and avg_response:
                            uptime_percent = (successful_checks / total_checks) * 100
                            try:
                                avg_response_time = float(avg_response)
                            except (ValueError, TypeError):
                                avg_response_time = None
                                
                            if avg_response_time and avg_response_time > 0 and uptime_percent > 50:
                                performance_score = avg_response_time * (1 + (100 - uptime_percent) / 100)
                                
                                endpoint_performance.append({
                                    'endpointName': endpoint_name,
                                    'workspaceName': workspace_name,
                                    'avgResponseTime': round(avg_response_time),
                                    'uptime': round(uptime_percent, 2),
                                    'performanceScore': performance_score
                                })

            endpoint_performance.sort(key=lambda x: x['performanceScore'])
            
            for item in endpoint_performance:
                del item['performanceScore']
            
            best_endpoints = endpoint_performance[:3]
            worst_endpoints = endpoint_performance[-3:] if len(endpoint_performance) > 3 else []
            worst_endpoints.reverse()

            return {
                'best': best_endpoints,
                'worst': worst_endpoints
            }

        except Exception:
            return {'best': [], 'worst': []}
        
    async def _get_user_endpoint_ids(self, user_id: str) -> List[str]:
        try:
            workspaces_response = self.supabase.table("workspaces").select("id").eq("user_id", user_id).execute()
            workspace_ids = [ws["id"] for ws in workspaces_response.data]
            
            if not workspace_ids:
                return []
            
            endpoints_response = self.supabase.table("endpoints").select("id").in_("workspace_id", workspace_ids).execute()
            return [ep["id"] for ep in endpoints_response.data]
        except Exception:
            return []