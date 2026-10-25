// frontend/app/journal/JournalManager.jsx

"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import ReactMarkdown from "react-markdown";
import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Eye,
  EyeOff,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  Trash2,
} from "lucide-react";

import { useConfig } from "@/hooks/ConfigContext";
import { notifyJournalViewStateChanged } from "@/utils/journalUiEvents";

const PAGE_SIZE = 50;

function formatJournalDate(value) {
  if (!value) return "Unknown date";

  // Avoid the browser's UTC interpretation turning YYYY-MM-DD into
  // the previous local calendar day in US time zones.
  const dateOnlyMatch = String(value).match(/^(\d{4})-(\d{2})-(\d{2})$/);

  if (dateOnlyMatch) {
    const [, year, month, day] = dateOnlyMatch;

    return new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "long",
      day: "numeric",
      timeZone: "UTC",
    }).format(new Date(Date.UTC(year, Number(month) - 1, day)));
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(date);
}

function VisibilityChip({ visibility }) {
  const isPrivate = visibility === "private";

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${
        isPrivate
          ? "border-amber-500/40 bg-amber-950/40 text-amber-200"
          : "border-emerald-500/40 bg-emerald-950/40 text-emerald-200"
      }`}
    >
      {isPrivate ? <LockKeyhole size={12} /> : <BookOpen size={12} />}
      {isPrivate ? "Private" : "Shared"}
    </span>
  );
}

function JournalBody({ body }) {
  return (
    <div className="space-y-4 text-[15px] leading-7 text-zinc-200">
      <ReactMarkdown
        components={{
          h1: ({ children }) => (
            <h1 className="mt-8 text-3xl font-semibold tracking-tight text-zinc-50 first:mt-0">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="mt-8 text-2xl font-semibold tracking-tight text-zinc-100">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="mt-6 text-xl font-semibold text-zinc-100">
              {children}
            </h3>
          ),
          p: ({ children }) => <p>{children}</p>,
          ul: ({ children }) => (
            <ul className="list-disc space-y-2 pl-6">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal space-y-2 pl-6">{children}</ol>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-violet-500/70 pl-4 italic text-zinc-300">
              {children}
            </blockquote>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              className="text-violet-300 underline decoration-violet-400/50 underline-offset-4 hover:text-violet-200"
              target="_blank"
              rel="noreferrer"
            >
              {children}
            </a>
          ),
          code: ({ inline, children }) =>
            inline ? (
              <code className="rounded bg-zinc-800 px-1.5 py-0.5 text-sm text-violet-200">
                {children}
              </code>
            ) : (
              <code className="block overflow-x-auto rounded-lg border border-zinc-800 bg-zinc-950 p-4 text-sm leading-6 text-zinc-200">
                {children}
              </code>
            ),
        }}
      >
        {body}
      </ReactMarkdown>
    </div>
  );
}

export default function JournalManager() {
  const { museProfile } = useConfig();

  const [journals, setJournals] = useState([]);
  const [total, setTotal] = useState(0);

  const [visibility, setVisibility] = useState("all");
  const [unviewedOnly, setUnviewedOnly] = useState(false);
  const [page, setPage] = useState(0);

  const [loadingCatalog, setLoadingCatalog] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [catalogError, setCatalogError] = useState(null);

  const [selectedJournal, setSelectedJournal] = useState(null);
  const [selectedJournalId, setSelectedJournalId] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState(null);
  const [deletingJournal, setDeletingJournal] = useState(false);

  const attemptedViewMarks = useRef(new Set());

  const museName =
    museProfile?.name?.[0]?.content ||
    museProfile?.name ||
    museProfile?.profile?.name ||
    "Muse";

  const offset = page * PAGE_SIZE;

  const fetchCatalog = useCallback(
    async ({ quiet = false } = {}) => {
      if (quiet) {
        setRefreshing(true);
      } else {
        setLoadingCatalog(true);
      }

      setCatalogError(null);

      try {
        const params = new URLSearchParams({
          limit: String(PAGE_SIZE),
          offset: String(offset),
        });

        if (visibility !== "all") {
          params.set("visibility", visibility);
        }

        if (unviewedOnly) {
          params.set("unviewed_only", "true");
        }

        const res = await fetch(`/api/journals/?${params.toString()}`);

        if (!res.ok) {
          throw new Error(`Failed to load journal catalog: HTTP ${res.status}`);
        }

        const data = await res.json();

        setJournals(data.journals || []);
        setTotal(Number(data.total) || 0);
      } catch (error) {
        console.error(error);
        setCatalogError(error.message || "Failed to load journal catalog.");
        setJournals([]);
        setTotal(0);
      } finally {
        setLoadingCatalog(false);
        setRefreshing(false);
      }
    },
    [offset, unviewedOnly, visibility]
  );

  useEffect(() => {
    fetchCatalog();
  }, [fetchCatalog]);

  const setJournalViewState = useCallback(
    async (journalEntryId, viewed) => {
      const res = await fetch(
        `/api/journals/${encodeURIComponent(journalEntryId)}/view-state`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ viewed }),
        }
      );

      if (!res.ok) {
        throw new Error(
          `Failed to update journal view state: HTTP ${res.status}`
        );
      }

      const data = await res.json();
      const updatedJournal = data.journal;

      if (!updatedJournal) {
        throw new Error("Journal view-state response did not include a journal.");
      }

      setSelectedJournal((current) =>
        current?.journal_entry_id === journalEntryId
          ? updatedJournal
          : current
      );

      setJournals((current) =>
        current.map((journal) =>
          journal.journal_entry_id === journalEntryId
            ? {
                ...journal,
                viewed_at: updatedJournal.viewed_at,
              }
            : journal
        )
      );

      notifyJournalViewStateChanged();

      return updatedJournal;
    },
    []
  );

  const selectJournal = useCallback(async (journalEntryId) => {
    setSelectedJournalId(journalEntryId);
    setSelectedJournal(null);
    setDetailError(null);
    setLoadingDetail(true);

    try {
      const res = await fetch(
        `/api/journals/${encodeURIComponent(journalEntryId)}`
      );

      if (!res.ok) {
        throw new Error(`Failed to load journal entry: HTTP ${res.status}`);
      }

      const data = await res.json();

      if (!data.journal) {
        throw new Error("Journal detail response did not include a journal.");
      }

      setSelectedJournal(data.journal);
    } catch (error) {
      console.error(error);
      setDetailError(error.message || "Failed to load journal entry.");
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  // Effects run after React has committed the selected detail to the DOM.
  // That makes opening the page—not merely fetching/preloading it—the
  // meaningful boundary for marking it viewed.
  useEffect(() => {
    const journalEntryId = selectedJournal?.journal_entry_id;

    if (
      !journalEntryId ||
      selectedJournal.viewed_at ||
      attemptedViewMarks.current.has(journalEntryId)
    ) {
      return;
    }

    attemptedViewMarks.current.add(journalEntryId);

    setJournalViewState(journalEntryId, true).catch((error) => {
      console.warn("Could not mark journal entry viewed:", error);
    });
  }, [selectedJournal, setJournalViewState]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const hasPreviousPage = page > 0;
  const hasNextPage = offset + journals.length < total;

  const catalogSummary = useMemo(() => {
    if (total === 1) return "1 journal entry";
    return `${total} journal entries`;
  }, [total]);

  function changeFilters({ nextVisibility, nextUnviewedOnly }) {
    setVisibility(nextVisibility);
    setUnviewedOnly(nextUnviewedOnly);
    setPage(0);
    setSelectedJournal(null);
    setSelectedJournalId(null);
    setDetailError(null);
  }

  async function handleMarkUnread() {
    if (!selectedJournal?.journal_entry_id) return;

    try {
      await setJournalViewState(selectedJournal.journal_entry_id, false);
    } catch (error) {
      console.error(error);
      setDetailError(error.message || "Failed to mark journal unread.");
    }
  }

  async function handleDelete() {
    if (!selectedJournal?.journal_entry_id || deletingJournal) return;

    const journalTitle = selectedJournal.title || "Untitled journal";

    const confirmed = window.confirm(
      `Delete "${journalTitle}"?\n\n` +
        "It will disappear from the Journal catalog and semantic recall. " +
        "The current implementation uses a soft delete, so it can still be " +
        "restored later through backend tooling, but this screen does not yet " +
        "offer an Undo button."
    );

    if (!confirmed) return;

    setDeletingJournal(true);
    setDetailError(null);

    try {
      const res = await fetch(
        `/api/journals/${encodeURIComponent(
          selectedJournal.journal_entry_id
        )}`,
        {
          method: "DELETE",
        }
      );

      if (!res.ok) {
        throw new Error(`Failed to delete journal entry: HTTP ${res.status}`);
      }

      const deletedJournalId = selectedJournal.journal_entry_id;

      setSelectedJournal(null);
      setSelectedJournalId(null);

      // Keep the visible catalog responsive even before the refresh completes.
      setJournals((current) =>
        current.filter(
          (journal) => journal.journal_entry_id !== deletedJournalId
        )
      );
      setTotal((current) => Math.max(0, current - 1));

      // A deleted unviewed item may change the persistent tab badge.
      notifyJournalViewStateChanged();

      // Reconcile pagination/filter totals with the authoritative backend.
      await fetchCatalog({ quiet: true });
    } catch (error) {
      console.error(error);
      setDetailError(error.message || "Failed to delete journal entry.");
    } finally {
      setDeletingJournal(false);
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#090913] text-zinc-100">
      <header className="border-b border-zinc-800 bg-[#11111f] px-6 py-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">
              {museName}&apos;s Journal
            </h1>

            <p className="mt-1 max-w-3xl text-sm text-zinc-400">
              A record of {museName}&apos;s reflections. Shared entries can be
              read here; private entries remain visibly present but keep their
              bodies private.
            </p>
          </div>

          <button
            type="button"
            onClick={() => fetchCatalog({ quiet: true })}
            className="inline-flex items-center gap-2 rounded-md border border-zinc-700 px-4 py-2 text-sm text-zinc-200 transition hover:bg-zinc-800"
          >
            <RefreshCw
              size={16}
              className={refreshing ? "animate-spin text-violet-300" : ""}
            />
            Refresh
          </button>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <select
            value={visibility}
            onChange={(event) =>
              changeFilters({
                nextVisibility: event.target.value,
                nextUnviewedOnly: unviewedOnly,
              })
            }
            className="rounded-md border border-zinc-700 bg-[#16162a] px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500"
          >
            <option value="all">All entries</option>
            <option value="shared">Shared only</option>
            <option value="private">Private only</option>
          </select>

          <label className="flex cursor-pointer items-center gap-2 text-sm text-zinc-300">
            <input
              type="checkbox"
              checked={unviewedOnly}
              onChange={(event) =>
                changeFilters({
                  nextVisibility: visibility,
                  nextUnviewedOnly: event.target.checked,
                })
              }
              className="h-4 w-4 rounded border-zinc-600 bg-[#16162a] text-violet-500 focus:ring-violet-500"
            />
            Unviewed only
          </label>

          <span className="text-sm text-zinc-500">{catalogSummary}</span>
        </div>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-1 xl:grid-cols-[22rem_minmax(0,1fr)]">
        <section className="min-h-0 overflow-y-auto border-b border-zinc-800 bg-[#0d0d18] xl:border-b-0 xl:border-r">
          {loadingCatalog ? (
            <div className="flex min-h-[260px] items-center justify-center gap-3 text-zinc-300">
              <LoaderCircle size={22} className="animate-spin text-violet-300" />
              Loading journal…
            </div>
          ) : catalogError ? (
            <div className="m-4 rounded-xl border border-red-900/70 bg-red-950/20 p-4 text-sm text-red-200">
              {catalogError}
            </div>
          ) : journals.length === 0 ? (
            <div className="m-4 flex min-h-[260px] flex-col items-center justify-center rounded-xl border border-zinc-800 bg-zinc-950/40 p-6 text-center text-zinc-400">
              <BookOpen size={28} className="mb-3 text-violet-300" />
              No journal entries match these filters.
            </div>
          ) : (
            <div className="p-3">
              {journals.map((journal) => {
                const isSelected =
                  journal.journal_entry_id === selectedJournalId;
                const isUnviewed = !journal.viewed_at;

                return (
                  <button
                    type="button"
                    key={journal.journal_entry_id}
                    onClick={() => selectJournal(journal.journal_entry_id)}
                    className={`mb-2 w-full rounded-lg border p-4 text-left transition ${
                      isSelected
                        ? "border-violet-500/70 bg-violet-950/35"
                        : "border-zinc-800 bg-[#12121f] hover:border-zinc-600 hover:bg-[#181827]"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          {isUnviewed && (
                            <span
                              className="h-2 w-2 shrink-0 rounded-full bg-violet-300"
                              title="Unviewed"
                            />
                          )}

                          <h2
                            className={`truncate text-sm ${
                              isUnviewed
                                ? "font-semibold text-zinc-50"
                                : "font-medium text-zinc-200"
                            }`}
                          >
                            {journal.title || "Untitled journal"}
                          </h2>
                        </div>

                        <p className="mt-1 text-xs text-zinc-500">
                          {formatJournalDate(journal.entry_date)}
                        </p>
                      </div>

                      <VisibilityChip visibility={journal.visibility} />
                    </div>
                  </button>
                );
              })}
            </div>
          )}

          {!loadingCatalog && !catalogError && total > PAGE_SIZE && (
            <div className="flex items-center justify-between border-t border-zinc-800 px-4 py-3">
              <button
                type="button"
                disabled={!hasPreviousPage}
                onClick={() => {
                  setPage((current) => Math.max(0, current - 1));
                  setSelectedJournal(null);
                  setSelectedJournalId(null);
                }}
                className="inline-flex items-center gap-1 rounded-md border border-zinc-700 px-3 py-1.5 text-sm text-zinc-300 transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <ChevronLeft size={16} />
                Newer
              </button>

              <span className="text-xs text-zinc-500">
                Page {page + 1} of {pageCount}
              </span>

              <button
                type="button"
                disabled={!hasNextPage}
                onClick={() => {
                  setPage((current) => current + 1);
                  setSelectedJournal(null);
                  setSelectedJournalId(null);
                }}
                className="inline-flex items-center gap-1 rounded-md border border-zinc-700 px-3 py-1.5 text-sm text-zinc-300 transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Older
                <ChevronRight size={16} />
              </button>
            </div>
          )}
        </section>

        <section className="min-h-0 overflow-y-auto bg-[#090913]">
          {!selectedJournalId ? (
            <div className="flex min-h-full flex-col items-center justify-center p-8 text-center">
              <BookOpen size={34} className="mb-4 text-violet-300" />
              <h2 className="text-lg font-medium text-zinc-200">
                Choose an entry to read
              </h2>
              <p className="mt-2 max-w-md text-sm leading-6 text-zinc-500">
                The catalog keeps the whole archive visible, while the reading
                pane preserves the boundary around private pages.
              </p>
            </div>
          ) : loadingDetail ? (
            <div className="flex min-h-full items-center justify-center gap-3 text-zinc-300">
              <LoaderCircle size={22} className="animate-spin text-violet-300" />
              Opening journal…
            </div>
          ) : detailError ? (
            <div className="m-6 rounded-xl border border-red-900/70 bg-red-950/20 p-4 text-sm text-red-200">
              {detailError}
            </div>
          ) : selectedJournal ? (
            <article className="mx-auto max-w-4xl px-6 py-8 pb-20 md:px-10">
              <header className="border-b border-zinc-800 pb-6">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <h2 className="text-3xl font-semibold tracking-tight text-zinc-50">
                      {selectedJournal.title || "Untitled journal"}
                    </h2>

                    <p className="mt-2 text-sm text-zinc-500">
                      {formatJournalDate(selectedJournal.entry_date)}
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    <VisibilityChip visibility={selectedJournal.visibility} />

                    {selectedJournal.viewed_at && (
                      <button
                        type="button"
                        onClick={handleMarkUnread}
                        className="inline-flex items-center gap-2 rounded-md border border-zinc-700 px-3 py-1.5 text-sm text-zinc-300 transition hover:bg-zinc-800"
                        title="Use unread as a deliberate return-to-this marker."
                      >
                        <EyeOff size={16} />
                        Mark unread
                      </button>
                    )}

                    <button
                      type="button"
                      onClick={handleDelete}
                      disabled={deletingJournal}
                      className="inline-flex items-center gap-2 rounded-md border border-red-900/70 bg-red-950/20 px-3 py-1.5 text-sm text-red-200 transition hover:bg-red-950/45 disabled:cursor-not-allowed disabled:opacity-50"
                      title="Remove this entry from the Journal and semantic recall."
                    >
                      {deletingJournal ? (
                        <LoaderCircle size={16} className="animate-spin" />
                      ) : (
                        <Trash2 size={16} />
                      )}
                      {deletingJournal ? "Deleting…" : "Delete"}
                    </button>

                  </div>
                </div>
              </header>

              {selectedJournal.body_available ? (
                <div className="pt-8">
                  <JournalBody body={selectedJournal.body || ""} />
                </div>
              ) : (
                <div className="mt-8 rounded-xl border border-amber-500/30 bg-amber-950/15 p-6">
                  <div className="flex items-start gap-4">
                    <LockKeyhole
                      size={24}
                      className="mt-0.5 shrink-0 text-amber-300"
                    />
                    <div>
                      <h3 className="font-medium text-amber-100">
                        Private journal entry
                      </h3>
                      <p className="mt-2 text-sm leading-6 text-amber-100/75">
                        This page is part of {museName}&apos;s journal catalog,
                        but its body is intentionally not shared here.
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {selectedJournal.viewed_at && (
                <div className="mt-10 flex items-center gap-2 text-xs text-zinc-600">
                  <Eye size={14} />
                  Viewed in the Journal
                </div>
              )}
            </article>
          ) : null}
        </section>
      </main>
    </div>
  );
}