from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.scheduler import start_scheduler, stop_scheduler
from routers import auth, dashboard, ingest, projects, webhooks, workspaces


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Waypoint", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(workspaces.router)
app.include_router(ingest.router)
app.include_router(projects.router)
app.include_router(webhooks.router)
app.include_router(dashboard.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
