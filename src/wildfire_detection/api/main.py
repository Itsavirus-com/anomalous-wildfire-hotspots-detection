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
from wildfire_detection.regions import initial_map_view

load_dotenv()

app = FastAPI(
    title="Wildfire Hotspot Anomaly Detection API",
    description=(
        "REST API for anomalous wildfire detection using global NASA FIRMS data, "
        "H3 aggregation, and Isolation Forest. Map clients should use "
        "`/api/map/config` (or `initial_view` on `/api/map`) to center on Indonesia at first load."
    ),
    version="1.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(alerts.router,   prefix="/api")
app.include_router(map.router,      prefix="/api")
app.include_router(cells.router,    prefix="/api")
app.include_router(stats.router,    prefix="/api")
app.include_router(pipeline.router, prefix="/api")


@app.get("/", tags=["Health"])
def root():
    return {
        "service": "Wildfire Detection API",
        "version": "1.2.0",
        "status": "running",
        "data_scope": "world",
        "initial_map_view": initial_map_view(),
        "docs": "/docs",
        "endpoints": {
            "map_config": "/api/map/config",
            "alerts": "/api/alerts",
            "map": "/api/map",
            "cells": "/api/cells/{h3_index}",
            "stats": "/api/stats",
            "pipeline": "/api/pipeline/status",
        },
    }


@app.get("/health", tags=["Health"])
def health():
    return JSONResponse({"status": "ok"})


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
