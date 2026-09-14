"""Application factory for the Local Diff Viewer."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.web.routes import router

STATIC_DIR = os.path.join(os.path.dirname(__file__), "web", "static")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Local Diff Viewer",
        description="A completely local folder/ZIP diff viewer -- no Git, no cloud.",
        version="1.0.0",
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(router)
    return app


app = create_app()
