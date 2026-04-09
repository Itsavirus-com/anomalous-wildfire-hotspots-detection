# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Wildfire Detection API — FastAPI Application Entry Point
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from .routers import alerts, map, cells, stats, pipeline

load_dotenv()

app = FastAPI(
    title="Wildfire Hotspot Anomaly Detection API",
    description=(
        "REST API for detecting anomalous wildfire activity in Indonesia. "
        "Uses NASA FIRMS satellite data, H3 spatial aggregation, and Isolation Forest ML."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ──────────────────────────────────────────────────────────────────
app.include_router(alerts.router,   prefix="/api")
app.include_router(map.router,      prefix="/api")
app.include_router(cells.router,    prefix="/api")
app.include_router(stats.router,    prefix="/api")
app.include_router(pipeline.router, prefix="/api")


# ─── Root ─────────────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
def root():
    return {
        "service": "Wildfire Detection API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "alerts":   "/api/alerts",
            "map":      "/api/map",
            "cells":    "/api/cells/{h3_index}",
            "stats":    "/api/stats",
            "pipeline": "/api/pipeline/status",
        },
    }


@app.get("/health", tags=["Health"])
def health():
    return JSONResponse({"status": "ok"})


# ─── Dev entrypoint ───────────────────────────────────────────────────────────
def main():
    import uvicorn
    uvicorn.run(
        "wildfire_detection.api.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", 8000)),
        reload=True,
    )


if __name__ == "__main__":
    main()
