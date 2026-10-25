// frontend/utils/journalUiEvents.js

export const JOURNAL_VIEW_STATE_CHANGED = "journal-view-state-changed";

export function notifyJournalViewStateChanged() {
  if (typeof window === "undefined") return;

  window.dispatchEvent(new Event(JOURNAL_VIEW_STATE_CHANGED));
}