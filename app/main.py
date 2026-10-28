import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.auth import auth_router
from app.routes.billing import billing_router, webhook_router
from app.routes.github import router as github_router

app = FastAPI(
    title="GitHub Analyzer Standalone",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(github_router, prefix="/github", tags=["GitHub Analyzer"])
app.include_router(auth_router, tags=["Authentication"])
app.include_router(billing_router, tags=["Billing"])
app.include_router(webhook_router, tags=["Billing Webhooks"])


@app.get("/")
def root():
    return {
        "message": "GitHub Analyzer Standalone Running",
        "status": "online",
    }


@app.get("/health")
def health():
    return {
        "message": "Server Healthy",
        "status": "ok",
    }
