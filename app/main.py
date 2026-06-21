import hmac
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.router import api_router
from app.config import settings
from app.services.overrides import seed_defaults


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(os.path.dirname(settings.runtime_db_path), exist_ok=True)
    seed_defaults()
    yield


app = FastAPI(title="Recipe Macros", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/admin", response_class=HTMLResponse)
async def admin(request: Request, key: str = Query("")):
    if not settings.admin_api_key or not hmac.compare_digest(key, settings.admin_api_key):
        return HTMLResponse("<h1>401</h1><p>Append ?key=YOUR_ADMIN_KEY to the URL</p>", status_code=401)
    return templates.TemplateResponse(request, "admin.html", {"api_key": key})


@app.get("/health")
async def health():
    return {"status": "ok"}
