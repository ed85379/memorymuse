# app/core/journaling/journal_router.py

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status as http_status
from pydantic import BaseModel

from app.core.journaling import journaling_core
from app.core.utils import serialize_doc


router = APIRouter(
    prefix="/api/journals",
    tags=["journals"],
)


class JournalViewStateRequest(BaseModel):
    """
    `viewed=True` means Ed deliberately opened this entry in the Journal UI.

    This is intentionally separate from journal editing. Opening a journal
    should not change its authorship/update timestamp.
    """
    viewed: bool


def _raise_journal_error(exc: Exception) -> None:
    """
    Convert expected core validation failures into honest API responses.

    Detail lookup handles its own not-found case explicitly, so ValueError
    here means malformed filters/pagination or an unexpected lifecycle issue.
    """
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    raise exc


def _get_journal_or_404(journal_entry_id: str) -> dict:
    """
    UI-safe journal detail lookup.

    This calls get_journal_entry_for_ui(), never read_journal_entry():
    private body ciphertext must not be decrypted merely because an HTTP
    endpoint needs to render a catalog/detail page.
    """
    journal = journaling_core.get_journal_entry_for_ui(journal_entry_id)

    if journal is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Journal entry {journal_entry_id!r} was not found.",
        )

    return journal


@router.get("/")
def get_journals(
    visibility: Literal["shared", "private", "all"] = "all",
    unviewed_only: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """
    Safe journal catalog listing.

    Results contain title/date/visibility/view state only—never body,
    ciphertext, provenance subject, or indexing internals.
    """
    try:
        result = journaling_core.list_journal_entries(
            visibility=None if visibility == "all" else visibility,
            unviewed_only=unviewed_only,
            limit=limit,
            offset=offset,
        )

        return {
            "journals": serialize_doc(result["entries"]),
            "total": result["total"],
            "limit": result["limit"],
            "offset": result["offset"],
        }
    except Exception as exc:
        _raise_journal_error(exc)


@router.get("/unviewed-count")
def get_unviewed_journal_count(
    visibility: Literal["shared", "private", "all"] = "all",
):
    """
    Lightweight count for the Journal tab badge.

    The frontend can call this on initial load and after a successful
    view-state mutation.
    """
    try:
        count = journaling_core.count_unviewed_journal_entries(
            visibility=None if visibility == "all" else visibility,
        )

        return {
            "count": count,
        }
    except Exception as exc:
        _raise_journal_error(exc)


@router.get("/{journal_entry_id}")
def get_journal(journal_entry_id: str):
    """
    Retrieve one UI-safe journal detail record.

    Shared entries include body.
    Private entries include catalog metadata only and body_available=False.
    This endpoint deliberately does not auto-mark the entry viewed; the
    frontend should do that after it successfully displays the detail panel.
    """
    return {
        "journal": serialize_doc(_get_journal_or_404(journal_entry_id)),
    }


@router.patch("/{journal_entry_id}/view-state")
def update_journal_view_state(
    journal_entry_id: str,
    payload: JournalViewStateRequest,
):
    """
    Mark a journal entry viewed or deliberately restore it to unviewed.

    The returned journal is re-fetched through the UI-safe projection rather
    than returning a raw Mongo update result.
    """
    _get_journal_or_404(journal_entry_id)

    try:
        if payload.viewed:
            journaling_core.mark_journal_entry_viewed(journal_entry_id)
        else:
            journaling_core.mark_journal_entry_unviewed(journal_entry_id)

        return {
            "journal": serialize_doc(
                _get_journal_or_404(journal_entry_id)
            ),
        }
    except Exception as exc:
        _raise_journal_error(exc)

@router.delete("/{journal_entry_id}")
def delete_journal(journal_entry_id: str):
    """
    Soft-delete one journal entry.

    The canonical Mongo document remains recoverable through the internal
    restore path, but the entry disappears from normal Journal UI listing
    and its derived semantic-recall points are removed.
    """
    _get_journal_or_404(journal_entry_id)

    try:
        deleted = journaling_core.delete_journal_entry(journal_entry_id)

        return {
            "journal_entry_id": journal_entry_id,
            "deleted_at": deleted.get("deleted_at"),
        }
    except Exception as exc:
        _raise_journal_error(exc)