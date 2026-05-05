"""Schemas for referral endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class ReferralStatsResponse(BaseModel):
    invited: int
    earned_kopecks: int
    ref_link: str
