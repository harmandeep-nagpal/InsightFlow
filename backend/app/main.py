from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.routers.datasets import router as datasets_router
from app.config import settings
from app.database.connection import engine
from app.database.dependencies import get_db


app = FastAPI(
    title=settings.app_name,
    description="AI-powered business analytics assistant",
    version=settings.app_version,
)
app.include_router(datasets_router)

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "environment": settings.environment,
    }


@app.get("/health/db")
def database_health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "connected",
    }