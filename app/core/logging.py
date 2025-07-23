# app/core/logging.py
import logging
import structlog
from typing import Any, Dict
from app.core.config import settings


def setup_logging() -> None:
    """Configure structured logging for the application"""
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, settings.log_level.upper()),
    )
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance"""
    return structlog.get_logger(name)


class SchedulerLogger:
    """Specialized logger for scheduler operations"""
    
    def __init__(self):
        self.logger = get_logger("scheduler")
    
    def startup(self, endpoint_count: int, cache_size_mb: float) -> None:
        self.logger.info(
            "Scheduler initialized",
            endpoint_count=endpoint_count,
            cache_size_mb=round(cache_size_mb, 2)
        )
    
    def cache_update(self, operation: str, endpoint_id: str, endpoint_name: str) -> None:
        self.logger.info(
            "Cache updated",
            operation=operation,
            endpoint_id=endpoint_id,
            endpoint_name=endpoint_name
        )
    
    def check_queued(self, endpoint_id: str, queue_size: int) -> None:
        self.logger.debug(
            "Endpoint check queued",
            endpoint_id=endpoint_id,
            queue_size=queue_size
        )
    
    def check_completed(self, endpoint_id: str, success: bool, response_time_ms: int, status_code: int = None) -> None:
        self.logger.info(
            "Endpoint check completed",
            endpoint_id=endpoint_id,
            success=success,
            response_time_ms=response_time_ms,
            status_code=status_code
        )
    
    def check_failed(self, endpoint_id: str, error: str, attempt: int) -> None:
        self.logger.warning(
            "Endpoint check failed",
            endpoint_id=endpoint_id,
            error=error,
            attempt=attempt
        )
    
    def health_status_changed(self, is_healthy: bool, reason: str) -> None:
        level = "info" if is_healthy else "error"
        getattr(self.logger, level)(
            "System health status changed",
            is_healthy=is_healthy,
            reason=reason
        )
    
    def queue_warning(self, queue_size: int, threshold: int) -> None:
        self.logger.warning(
            "Queue size exceeds warning threshold",
            queue_size=queue_size,
            threshold=threshold
        )
    
    def cache_warning(self, cache_size: int, threshold: int) -> None:
        self.logger.warning(
            "Cache size exceeds warning threshold",
            cache_size=cache_size,
            threshold=threshold
        )
    
    def error(self, message: str, **kwargs) -> None:
        self.logger.error(message, **kwargs)
    
    def critical(self, message: str, **kwargs) -> None:
        self.logger.critical(message, **kwargs)