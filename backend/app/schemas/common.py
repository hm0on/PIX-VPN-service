"""Common schema bases."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    """Pydantic base configured to work with SQLAlchemy ORM rows."""

    model_config = ConfigDict(from_attributes=True)


class HealthResponse(BaseModel):
    status: str
    db: str
    redis: str


class OkResponse(BaseModel):
    ok: bool = True
