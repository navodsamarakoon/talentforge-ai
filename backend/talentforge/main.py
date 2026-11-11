from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from talentforge.api import router
from talentforge.cv_callbacks import router as cv_router
from talentforge.config import get_settings

settings = get_settings()
app = FastAPI(title="TalentForge AI API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(router, prefix="/api")
app.include_router(cv_router, prefix="/api")
