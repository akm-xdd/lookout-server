# app/main.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from app.core.config import settings, get_cors_origins
from app.routes.workspaces import router as workspace_router
from app.routes.endpoints import router as endpoint_router
from app.routes.user_stats import router as user_stats_router
from app.routes.dashboard import router as dashboard_router
from app.routes.scheduler_status import router as scheduler_router
from app.services.scheduler_manager import lifespan


def create_app() -> FastAPI:
    """Create and configure FastAPI application"""
    
    app = FastAPI(
        title=settings.project_name,
        version=settings.project_version,
        debug=settings.debug,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan
    )

    print(get_cors_origins())

    # Add HTTPS redirect middleware FIRST (only in production)
    if not settings.debug:
        app.add_middleware(HTTPSRedirectMiddleware)

    # CORS middleware (after HTTPS redirect)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Custom middleware to fix redirect headers
    # @app.middleware("http")
    # async def fix_redirect_headers(request: Request, call_next):
    #     response = await call_next(request)
        
    #     # Fix any Location headers that might use HTTP and remove trailing slashes
    #     if hasattr(response, 'headers') and 'location' in response.headers:
    #         location = response.headers['location']
    #         response.headers['location'] = location.replace('http://', 'https://').rstrip('/')
        
    #     return response

    # Include routers
    app.include_router(workspace_router, prefix="/api")
    app.include_router(endpoint_router, prefix="/api")
    app.include_router(user_stats_router, prefix="/api")
    app.include_router(dashboard_router, prefix="/api")
    app.include_router(scheduler_router, prefix="/api")

    # Health check endpoint
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "service": settings.project_name}

    # Root endpoint
    @app.get("/")
    async def root():
        return {
            "message": f"Welcome to {settings.project_name}",
            "version": settings.project_version,
            "docs_url": "/docs" if settings.debug else None
        }

    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        proxy_headers=True,
    )