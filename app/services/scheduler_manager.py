from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.services.endpoint_scheduler import EndpointScheduler
from app.db.supabase import get_supabase_admin
from app.core.config import settings
from app.core.logging import setup_logging, get_logger


class SchedulerManager:
    """
    Global scheduler manager for FastAPI integration.
    Handles scheduler lifecycle and provides global access.
    """
    
    def __init__(self):
        self.scheduler: Optional[EndpointScheduler] = None
        self.logger = get_logger("scheduler_manager")
    
    async def initialize(self) -> None:
        """Initialize the scheduler if enabled"""
        if not settings.scheduler_enabled:
            self.logger.info("Scheduler disabled in configuration")
            return
        
        try:
            # Get Supabase admin client for scheduler operations
            supabase = get_supabase_admin()
            
            # Create and initialize scheduler
            self.scheduler = EndpointScheduler(supabase)
            await self.scheduler.initialize()
            
            # Start the scheduler
            await self.scheduler.start()
            
            self.logger.info("Scheduler manager initialized successfully")
            
        except Exception as e:
            self.logger.error("Failed to initialize scheduler", error=str(e))
            raise
    
    async def shutdown(self) -> None:
        """Shutdown the scheduler gracefully"""
        if self.scheduler:
            try:
                await self.scheduler.stop()
                self.logger.info("Scheduler shutdown completed")
            except Exception as e:
                self.logger.error("Error during scheduler shutdown", error=str(e))
        else:
            self.logger.info("No scheduler to shutdown")
    
    def get_scheduler(self) -> Optional[EndpointScheduler]:
        """Get the active scheduler instance"""
        return self.scheduler
    
    def is_available(self) -> bool:
        """Check if scheduler is available and running"""
        return (
            self.scheduler is not None and 
            self.scheduler.is_initialized and 
            self.scheduler.is_running
        )


# Global scheduler manager instance
scheduler_manager = SchedulerManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Modern FastAPI lifespan context manager.
    Replaces deprecated @app.on_event() decorators.
    """
    # Setup logging first
    setup_logging()
    logger = get_logger("app_lifespan")
    
    # Startup
    logger.info("Application starting up...")
    try:
        await scheduler_manager.initialize()
        logger.info("Application startup completed")
    except Exception as e:
        logger.error("Application startup failed", error=str(e))
        raise
    
    yield  # Application runs here
    
    # Shutdown
    logger.info("Application shutting down...")
    try:
        await scheduler_manager.shutdown()
        logger.info("Application shutdown completed")
    except Exception as e:
        logger.error("Application shutdown failed", error=str(e))


def get_scheduler() -> Optional[EndpointScheduler]:
    """
    Dependency function to get the scheduler in FastAPI routes.
    Returns None if scheduler is not available.
    """
    return scheduler_manager.get_scheduler()


def notify_endpoint_created(endpoint_data: dict) -> None:
    """
    Notify scheduler of new endpoint creation.
    Call this from your endpoint creation API.
    """
    scheduler = scheduler_manager.get_scheduler()
    if scheduler:
        scheduler.on_endpoint_created(endpoint_data)


def notify_endpoint_updated(endpoint_id: str, updated_data: dict) -> None:
    """
    Notify scheduler of endpoint updates.
    Call this from your endpoint update API.
    """
    scheduler = scheduler_manager.get_scheduler()
    if scheduler:
        scheduler.on_endpoint_updated(endpoint_id, updated_data)


def notify_endpoint_deleted(endpoint_id: str) -> None:
    """
    Notify scheduler of endpoint deletion.
    Call this from your endpoint delete API.
    """
    scheduler = scheduler_manager.get_scheduler()
    if scheduler:
        scheduler.on_endpoint_deleted(endpoint_id)