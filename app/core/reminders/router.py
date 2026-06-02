# app/core/reminders/router.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional
from .reminders_core import handle_snooze, handle_skip, handle_toggle


router = APIRouter(prefix="/api/reminders", tags=["reminders"])

class ReminderActionPayload(BaseModel):
    action: Literal["snooze", "skip", "toggle"]
    snooze_until: Optional[str] = None   # ISO 8601
    skip_until: Optional[str] = None     # ISO 8601
    status: Optional[Literal["enabled", "disabled"]] = None

@router.post("/{reminder_id}/action")
def reminder_action(reminder_id: str, payload: ReminderActionPayload):
    # sanity: make sure path id and payload id don’t drift
    base_payload = {"id": reminder_id}

    if payload.action == "snooze":
        if not payload.snooze_until:
            raise HTTPException(status_code=400, detail="snooze_until is required for snooze")
        return handle_snooze(
            {
                **base_payload,
                "snooze_until": payload.snooze_until,
            }
        )

    if payload.action == "skip":
        if not payload.skip_until:
            raise HTTPException(status_code=400, detail="skip_until is required for skip")
        return handle_skip(
            {
                **base_payload,
                "skip_until": payload.skip_until,
            }
        )

    if payload.action == "toggle":
        if not payload.status:
            raise HTTPException(status_code=400, detail="status is required for toggle")
        return handle_toggle(
            {
                **base_payload,
                "status": payload.status,
            }
        )

    raise HTTPException(status_code=400, detail="Unknown action")