import React, { useMemo, useState } from "react";
import { useFeatures } from '@/hooks/FeaturesContext';
import {
  Eye,
  EyeOff,
  EyeClosed,
  DoorClosed,
  DoorClosedLocked,
  Lock,
  Archive,
  ArchiveRestore,
  Trash2,
  ArrowUpDown,
  Split,
  Pencil,
  Clapperboard,
  Plus,
   } from "lucide-react";
import {
  clearOpenThread,
  setThreadPrivate,
  setThreadHidden,
  setThreadArchived,
  setThreadTitle,
  setThreadScene,
  updateThread,
  updateSingleThreadInState,
  upsertThreadInState,
  deleteThread,
  deleteThreadWithMessages,
  createThread,
   } from '@/utils/threadActions'

export default function ThreadManagerPanel({
  threads,
  setThreads,
  fetchThreads,
  setMessages,
  setThreadMessages,
  setThreadManagerOpen,
  openThreadId,
  setOpenThreadId,
  setActiveTab,
  updateThreadsState,
  onClose, // optional, if you want a close button on the panel itself
}) {
  const { adminConfig, adminLoading } = useFeatures();
  const mm = adminConfig?.mm_features || {};
  const enablePublic = !!mm.ENABLE_PUBLIC_INTERFACES ;

  const [sortField, setSortField] = React.useState("title"); // "title" | "created_at"
  const [sortDir, setSortDir] = React.useState("asc");       // "asc" | "desc"
  const [showArchived, setShowArchived] = React.useState(false);
  const [activeDeleteThreadId, setActiveDeleteThreadId] = React.useState(null);
  const [deleteScope, setDeleteScope] = React.useState("thread-only");
  const [editingThreadId, setEditingThreadId] = React.useState(null);
  const [editingTitle, setEditingTitle] = React.useState("");
  const [createPanelOpen, setCreatePanelOpen] = React.useState(false);
  const [newThreadTitle, setNewThreadTitle] = React.useState("");
  const [managingThreadId, setManagingThreadId] = React.useState(null);

  const managingThread = managingThreadId
    ? threads.find(t => t.thread_id === managingThreadId)
    : null;

  const handleCreateThread = async () => {
    const title = newThreadTitle.trim();

    const threadId = await createThread({
      setOpenThreadId,
      setActiveTab,
      updateThreadsState,
      refreshThreads: fetchThreads,
      title: title || undefined,
      setThreads,
      type: "thread",
    });

    if (threadId) {
      setNewThreadTitle("");
      setCreatePanelOpen(false);
      setThreadManagerOpen(false);
    }
  };

  const handleCreateScene = async () => {
    const title = newThreadTitle.trim();

    const threadId = await createThread({
      setOpenThreadId,
      setActiveTab,
      updateThreadsState,
      refreshThreads: fetchThreads,
      title: title || "New Scene",
      setThreads,
      type: "scene",
    });

    if (threadId) {
      setNewThreadTitle("");
      setCreatePanelOpen(false);
      setThreadManagerOpen(false);
    }
  };

  const handleOpenThread = (threadId) => {
    setOpenThreadId(threadId);
    setActiveTab("thread");
    setThreadManagerOpen(false);
    updateThreadsState({ open_thread_id: threadId });
  }

  const closeDialog = () => {
    setActiveDeleteThreadId(null);
    setDeleteScope("thread-only");
  };

  const confirmDelete = async () => {
    if (!activeDeleteThreadId) return;

    if (deleteScope === "thread-only") {
      await handleDeleteThread(activeDeleteThreadId);
    } else {
      await handleDeleteThreadWithMessages(activeDeleteThreadId);
    }
    closeDialog();
  };

  const activeThread = activeDeleteThreadId
    ? threads.find(t => t.thread_id === activeDeleteThreadId)
    : null;

  const handleEditTitle = async (threadId, title) => {
    try {
      const updated = await setThreadTitle(threadId, title);
      upsertThreadInState(setThreads, updated);
    } catch (err) {
      console.error("Failed to modify thread:", err);
      // Optionally show a toast / error UI
    }
  };

  const hideThread = async (threadId, isHidden) => {
    try {
      const updated = await setThreadHidden(threadId, isHidden);
      upsertThreadInState(setThreads, updated);
    } catch (err) {
      console.error("Failed to modify thread:", err);
      // Optionally show a toast / error UI
    }
  };

  const setPrivate = async (threadId, isPrivate) => {
    try {
      const updated = await setThreadPrivate(threadId, isPrivate);
      upsertThreadInState(setThreads, updated);
    } catch (err) {
      console.error("Failed to modify thread:", err);
      // Optionally show a toast / error UI
    }
  };

  const archiveThread = async (threadId, isArchived) => {
    try {
      if (openThreadId === threadId) {
        clearOpenThread({
          setOpenThreadId,
          setActiveTab,
          updateThreadsState,
        })
      }
      const updated = await setThreadArchived(threadId, isArchived);
      upsertThreadInState(setThreads, updated);
    } catch (err) {
      console.error("Failed to modify thread:", err);
      // Optionally show a toast / error UI
    }
  };

  const handleDeleteThread = async (threadId) => {
    try {
      // 1) Call API and capture response
      const res = await deleteThread(threadId);
      const { message_ids = [] } = res;   // destructure from res.data

      // 2) Refresh the thread list from server
      fetchThreads();

      // 3) Optimistic UI update in main messages list
      if (message_ids.length) {
        setMessages(prev =>
          prev.map(m => {
            if (!message_ids.includes(m.message_id)) return m;
            const existing = m.thread_ids || [];
            if (!existing.length) return m;
            return {
              ...m,
              thread_ids: existing.filter(tid => tid !== threadId),
            };
          })
        );

        // 4) Optimistic UI update in thread-specific list (if present)
        if (setThreadMessages) {
          setThreadMessages(prev =>
            prev.map(m => {
              if (!message_ids.includes(m.message_id)) return m;
              const existing = m.thread_ids || [];
              if (!existing.length) return m;
              return {
                ...m,
                thread_ids: existing.filter(tid => tid !== threadId),
              };
            })
          );
        }
      }
    } catch (err) {
      console.error("Failed to modify thread:", err);
      // optional: toast / error UI
    }
  };

  const handleDeleteThreadWithMessages = async (threadId) => {
    try {
      // 1) Call API and capture response
      const res = await deleteThreadWithMessages(threadId);
      const { message_ids = [] } = res;   // destructure from res.data

      // 2) Refresh the thread list from server
      fetchThreads();

      // 3) Optimistic UI update in main messages list
      if (message_ids.length) {
        setMessages(prev =>
          prev.map(m => {
            if (!message_ids.includes(m.message_id)) return m;
            const existing = m.thread_ids || [];
            if (!existing.length) return m;
            return {
              ...m,
              thread_ids: existing.filter(tid => tid !== threadId),
              is_deleted: true,
            };
          })
        );

        // 4) Optimistic UI update in thread-specific list (if present)
        if (setThreadMessages) {
          setThreadMessages(prev =>
            prev.map(m => {
              if (!message_ids.includes(m.message_id)) return m;
              const existing = m.thread_ids || [];
              if (!existing.length) return m;
              return {
                ...m,
                thread_ids: existing.filter(tid => tid !== threadId),
                is_deleted: true,
              };
            })
          );
        }
      }
    } catch (err) {
      console.error("Failed to modify thread:", err);
      // optional: toast / error UI
    }
  };


  const sortedThreads = React.useMemo(() => {
    const copy = [...threads];

    copy.sort((a, b) => {
      let av, bv;

      if (sortField === "title") {
        av = (a.title || "").toLowerCase();
        bv = (b.title || "").toLowerCase();
      } else {
        // created_at
        av = new Date(a.created_at).getTime();
        bv = new Date(b.created_at).getTime();
      }

      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });

    return copy;
  }, [threads, sortField, sortDir]);

  const activeThreads = sortedThreads.filter(t => !t.is_archived);
  const archivedThreads = sortedThreads.filter(t => t.is_archived);

  const toggleSortField = () => {
    setSortField(prev => (prev === "title" ? "created_at" : "title"));
  };

  const toggleSortDir = () => {
    setSortDir(prev => (prev === "asc" ? "desc" : "asc"));
  };

  return (
    <div className="mt-2 rounded-md border border-neutral-800 bg-neutral-950/95 shadow-lg text-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-neutral-800">
        <div className="flex items-center gap-2 text-neutral-300">
          <Split className="w-4 h-4" />
          <span className="font-semibold">Thread Manager</span>


        <button
          type="button"
          onClick={() => setCreatePanelOpen(prev => !prev)}
          className="inline-flex items-center gap-1 rounded border border-purple-500/60 px-2 py-1 text-xs text-purple-200 hover:bg-purple-500/10"
        >
          <Plus size={13} />
          Create
        </button>
        </div>

        <div className="flex items-center gap-2 text-xs text-neutral-400">
          <button
            type="button"
            onClick={toggleSortField}
            className="inline-flex items-center gap-1 hover:text-neutral-100"
            title="Toggle sort field"
          >
            <ArrowUpDown className="w-3 h-3" />
            <span>{sortField === "title" ? "Title" : "Date"}</span>
          </button>
          <button
            type="button"
            onClick={toggleSortDir}
            className="hover:text-neutral-100"
            title="Toggle sort direction"
          >
            {sortDir === "asc" ? "↑" : "↓"}
          </button>
        </div>
      </div>
      {createPanelOpen && (
        <div className="px-3 py-2 border-b border-neutral-800 bg-neutral-950/70 space-y-2">
          <input
            value={newThreadTitle}
            onChange={e => setNewThreadTitle(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleCreateThread();
              } else if (e.key === "Escape") {
                setCreatePanelOpen(false);
                setNewThreadTitle("");
              }
            }}
            placeholder="Title, optional"
            className="w-full rounded bg-neutral-900/80 px-2 py-1 text-sm text-neutral-100 border border-neutral-700 focus:outline-none focus:ring-1 focus:ring-purple-500"
          />

          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleCreateThread}
              className="inline-flex items-center gap-1 rounded border border-purple-500/60 px-2 py-1 text-xs text-purple-200 hover:bg-purple-500/10"
            >
              <Split size={13} />
              Thread
            </button>

            <button
              type="button"
              onClick={handleCreateScene}
              className="inline-flex items-center gap-1 rounded border border-purple-500/60 px-2 py-1 text-xs text-purple-200 hover:bg-purple-500/10"
            >
              <Clapperboard size={13} />
              Scene
            </button>
          </div>
        </div>
      )}

      {/* Active threads */}
      <div className="max-h-64 overflow-y-auto">
        {activeThreads.length === 0 ? (
          <div className="px-3 py-2 text-neutral-500 italic">
            No active threads yet.
          </div>
        ) : (
          activeThreads.map(thread => (
            <div
              key={thread.thread_id}
              className="flex items-center justify-between px-3 py-1.5 border-b border-neutral-900/60 hover:bg-neutral-900/40"
            >
              <div className="min-w-0">
                <div className="flex items-start gap-1">
                  {/* Tiny pencil icon to trigger edit */}
                  {editingThreadId !== thread.thread_id && (
                    <button
                      type="button"
                      onClick={e => {
                        e.stopPropagation(); // don’t trigger row click
                        setEditingThreadId(thread.thread_id);
                        setEditingTitle(thread.title || "");
                      }}
                      className="shrink-0 p-0.5 rounded text-neutral-500 hover:text-purple-300 hover:bg-neutral-800"
                      title="Edit title"
                    >
                      <Pencil className="w-3 h-3" />
                    </button>
                  )}
                  <div className="flex-1 min-w-0">
                    {editingThreadId === thread.thread_id ? (
                      <input
                        type="text"
                        autoFocus
                        value={editingTitle}
                        onChange={e => setEditingTitle(e.target.value)}
                        onBlur={() => {
                          const trimmed = editingTitle.trim();
                          handleEditTitle(thread.thread_id, trimmed || null);
                          setEditingThreadId(null);
                          setEditingTitle("");
                        }}
                        onKeyDown={e => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            const trimmed = editingTitle.trim();
                            handleEditTitle(thread.thread_id, trimmed || null);
                            setEditingThreadId(null);
                            setEditingTitle("");
                          } else if (e.key === "Escape") {
                            setEditingThreadId(null);
                            setEditingTitle("");
                          }
                        }}
                        className="w-full rounded bg-neutral-900/80 px-1.5 py-0.5 text-sm text-neutral-100 border border-neutral-700 focus:outline-none focus:ring-1 focus:ring-purple-500"
                      />
                    ) : (
                      <div
                        className="truncate text-neutral-100"
                        title={thread.title || "(untitled thread)"}
                      >
                        {thread.title || "(untitled thread)"}
                        {thread.type === "scene" && (
                          <span className="ml-1 rounded border border-purple-500/40 px-1 py-0.5 text-[10px] uppercase tracking-wide text-purple-300">
                            Scene
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
                <div className="text-[11px] text-neutral-500">
                  {new Date(thread.created_at).toLocaleString()}
                </div>
              </div>

              <div className="ml-2 flex items-center gap-1 shrink-0">

                <button
                  type="button"
                  onClick={() => setManagingThreadId(thread.thread_id)}
                  className="px-1.5 py-0.5 rounded border border-neutral-700 text-[11px] text-neutral-300 hover:bg-neutral-800"
                >
                  Setup
                </button>

                {/* Open */}
                <button
                  type="button"
                  onClick={() => handleOpenThread(thread.thread_id)}
                  className="px-1.5 py-0.5 rounded border border-purple-500/60 text-[11px] text-purple-200 hover:bg-purple-500/10"
                  title="Open thread"
                >
                  Open
                </button>


                {/* Hide / unhide */}
                <button
                  type="button"
                  onClick={() => hideThread(thread.thread_id, !thread.is_hidden)}
                  className={`p-1 rounded ${
                    thread.is_hidden
                      ? "text-neutral-500 hover:text-neutral-200"
                      : "text-neutral-400 hover:text-neutral-100"
                  }`}
                  title={thread.is_hidden ? "Unhide thread" : "Hide thread"}
                >
                  {thread.is_hidden ? <EyeOff size={14} className="text-red-400" /> : <Eye size={14} />}

                </button>

                {/* Private toggle */}
                {enablePublic && (
                <button
                  type="button"
                  onClick={() => setPrivate(thread.thread_id, !thread.is_private)}
                  className={`p-1 rounded ${
                    thread.is_private
                      ? "text-amber-400 hover:text-amber-300"
                      : "text-neutral-400 hover:text-neutral-100"
                  }`}
                  title={thread.is_private ? "Mark as public" : "Mark as private"}
                >
                  {thread.is_private ? <DoorClosedLocked size={14} className="text-red-400" /> : <DoorClosed size={14} />}
                </button>
                )}
                {/* Archive */}
                <button
                  type="button"
                  onClick={() => archiveThread(thread.thread_id, !thread.is_archived)}
                  className="p-1 rounded text-neutral-400 hover:text-neutral-100"
                  title="Archive thread"
                >
                  {thread.is_archived ? <ArchiveRestore size={14} className="text-red-400" /> : <Archive size={14} />}
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Archived section toggle */}
      <button
        type="button"
        onClick={() => setShowArchived(prev => !prev)}
        className="flex w-full items-center justify-between px-3 py-1.5 border-t border-neutral-800 text-xs text-neutral-400 hover:text-neutral-100 hover:bg-neutral-900/60"
      >
        <span>Show archived</span>
        <span>{showArchived ? "▲" : "▼"}</span>
      </button>

      {/* Archived list */}
      {showArchived && (
        <div className="max-h-48 overflow-y-auto border-t border-neutral-900/80">
          {archivedThreads.length === 0 ? (
            <div className="px-3 py-2 text-neutral-500 italic">
              No archived threads.
            </div>
          ) : (
            archivedThreads.map(thread => (
              <div
                key={thread.thread_id}
                className="flex items-center justify-between px-3 py-1.5 border-b border-neutral-900/60 hover:bg-neutral-900/40"
              >
                <div className="min-w-0">
                  <div className="flex items-start gap-1">
                    {/* Tiny pencil icon to trigger edit */}
                    {editingThreadId !== thread.thread_id && (
                      <button
                        type="button"
                        onClick={e => {
                          e.stopPropagation(); // don’t trigger row click
                          setEditingThreadId(thread.thread_id);
                          setEditingTitle(thread.title || "");
                        }}
                        className="shrink-0 p-0.5 rounded text-neutral-500 hover:text-purple-300 hover:bg-neutral-800"
                        title="Edit title"
                      >
                        <Pencil className="w-3 h-3" />
                      </button>
                    )}
                    <div className="flex-1 min-w-0">
                      {editingThreadId === thread.thread_id ? (
                        <input
                          type="text"
                          autoFocus
                          value={editingTitle}
                          onChange={e => setEditingTitle(e.target.value)}
                          onBlur={() => {
                            const trimmed = editingTitle.trim();
                            handleEditTitle(thread.thread_id, trimmed || null);
                            setEditingThreadId(null);
                            setEditingTitle("");
                          }}
                          onKeyDown={e => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              const trimmed = editingTitle.trim();
                              handleEditTitle(thread.thread_id, trimmed || null);
                              setEditingThreadId(null);
                              setEditingTitle("");
                            } else if (e.key === "Escape") {
                              setEditingThreadId(null);
                              setEditingTitle("");
                            }
                          }}
                          className="w-full rounded bg-neutral-900/80 px-1.5 py-0.5 text-sm text-neutral-100 border border-neutral-700 focus:outline-none focus:ring-1 focus:ring-purple-500"
                        />
                      ) : (
                        <div
                          className="truncate text-neutral-100"
                          title={thread.title || "(untitled thread)"}
                        >
                          {thread.title || "(untitled thread)"}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="text-[11px] text-neutral-500">
                    {new Date(thread.created_at).toLocaleString()}
                  </div>
                </div>

                <div className="ml-2 flex items-center gap-1 shrink-0">
                  {/* Open + unarchive in one */}
                  <button
                    type="button"
                    onClick={() => {
                      archiveThread(thread.thread_id, !thread.is_archived);
                      handleOpenThread(thread.thread_id);
                    }}
                    className="px-1.5 py-0.5 rounded border border-purple-500/60 text-[11px] text-purple-200 hover:bg-purple-500/10"
                    title="Unarchive and open"
                  >
                    Open
                  </button>

                  {/* Unarchive only */}
                  <button
                    type="button"
                    onClick={() => archiveThread(thread.thread_id, !thread.is_archived)}
                    className="p-1 rounded text-neutral-400 hover:text-neutral-100"
                    title="Unarchive"
                  >
                    <ArchiveRestore className="w-3 h-3" />
                  </button>

                  {/* Permanently delete */}
                  <button
                    type="button"
                    onClick={() => setActiveDeleteThreadId(thread.thread_id)}
                    className="p-1 rounded text-red-500 hover:text-red-300"
                    title="Permanently delete"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}

          {/* Inline confirmation dialog */}
      {activeDeleteThreadId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-full max-w-sm rounded-md border border-neutral-800 bg-neutral-950 p-4 shadow-xl">
            <h3 className="text-sm font-semibold text-neutral-100 mb-2">
              Delete thread “{activeThread?.title || "this thread"}”?
            </h3>

            <p className="text-xs text-neutral-400 mb-3">
              Choose what to delete. This action can’t be undone.
            </p>

            <div className="space-y-2 mb-3">
              <label className="flex items-start gap-2 text-xs text-neutral-200">
                <input
                  type="radio"
                  value="thread-only"
                  checked={deleteScope === "thread-only"}
                  onChange={() => setDeleteScope("thread-only")}
                  className="mt-0.5"
                />
                <span>
                  <span className="font-semibold block">
                    Delete thread only
                  </span>
                  <span className="text-neutral-400">
                    Remove this thread from the list. Messages stay in your main history.
                  </span>
                </span>
              </label>

              <label className="flex items-start gap-2 text-xs text-neutral-200">
                <input
                  type="radio"
                  value="thread-and-messages"
                  checked={deleteScope === "thread-and-messages"}
                  onChange={() => setDeleteScope("thread-and-messages")}
                  className="mt-0.5"
                />
                <span>
                  <span className="font-semibold block">
                    Delete thread and hide messages
                  </span>
                  <span className="text-neutral-400">
                    Remove the thread and soft‑delete its messages from history.
                  </span>
                </span>
              </label>
            </div>

            <p className="text-[11px] font-semibold text-red-400 mb-3">
              The thread itself cannot be recovered.
            </p>

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={closeDialog}
                className="px-2.5 py-1 rounded border border-neutral-700 text-xs text-neutral-200 hover:bg-neutral-800"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmDelete}
                className="px-2.5 py-1 rounded bg-red-600 text-xs text-white hover:bg-red-500"
              >
                {deleteScope === "thread-only"
                  ? "Delete thread"
                  : "Delete thread + hide messages"}
              </button>
            </div>
          </div>
        </div>
      )}
      {managingThread && (
        <ThreadManagePopup
          thread={managingThread}
          onClose={() => setManagingThreadId(null)}
          setThreads={setThreads}
          fetchThreads={fetchThreads}
          openThreadId={openThreadId}
          setOpenThreadId={setOpenThreadId}
          setActiveTab={setActiveTab}
          updateThreadsState={updateThreadsState}
        />
      )}
    </div>
  );
}

const SCENE_STATUS_OPTIONS = [
  { value: "active", label: "Active" },
  { value: "paused", label: "Paused" },
  { value: "complete", label: "Complete" },
];

const SCENE_FIELD_OPTIONS = [
  { key: "setting", label: "Setting", nsfwOnly: false },
  { key: "location", label: "Location", nsfwOnly: false },
  { key: "time", label: "Time", nsfwOnly: false },
  { key: "characters", label: "Characters", nsfwOnly: false },
  { key: "point_of_view", label: "Point of View", nsfwOnly: false },
  { key: "tone", label: "Tone", nsfwOnly: false },
  { key: "genre", label: "Genre", nsfwOnly: false },
  { key: "opening_situation", label: "Opening Situation", nsfwOnly: false },
  { key: "relationship_context", label: "Relationship Context", nsfwOnly: false },
  { key: "stakes", label: "Stakes", nsfwOnly: false },
  { key: "conflict", label: "Conflict", nsfwOnly: false },
  { key: "boundaries", label: "Boundaries", nsfwOnly: false },
  { key: "continuity_notes", label: "Continuity Notes", nsfwOnly: false },
  { key: "desired_pacing", label: "Desired Pacing", nsfwOnly: false },
  { key: "image_style", label: "Image Style", nsfwOnly: false },

  { key: "desire_dynamic", label: "Desire Dynamic", nsfwOnly: true },
  { key: "explicitness_level", label: "Explicitness Level", nsfwOnly: true },
  { key: "sexual_boundaries", label: "Sexual Boundaries", nsfwOnly: true },
  { key: "hard_limits", label: "Hard Limits", nsfwOnly: true },
  { key: "kinks_interests", label: "Kinks / Interests", nsfwOnly: true },
  { key: "power_dynamic", label: "Power Dynamic", nsfwOnly: true },
  { key: "aftercare_tone", label: "Aftercare Tone", nsfwOnly: true },
  { key: "language_style", label: "Language Style", nsfwOnly: true },
];

function getSceneFieldLabel(key) {
  return SCENE_FIELD_OPTIONS.find(opt => opt.key === key)?.label || key;
}

function makeFieldId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }

  return `field_${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

function normalizeScene(scene) {
  return {
    premise: scene?.premise || "",
    nsfw: Boolean(scene?.nsfw),
    status: scene?.status || "active",
    fields: Array.isArray(scene?.fields) ? scene.fields : [],
    instructions: scene?.instructions ?? null,
  };
}

function ThreadManagePopup({
  thread,
  onClose,
  setThreads,
  fetchThreads,
}) {
  const [guidanceDraft, setGuidanceDraft] = React.useState(
    () => thread.guidance || ""
  );
  const isScene = thread.type === "scene";

  const [sceneDraft, setSceneDraft] = React.useState(() =>
    normalizeScene(thread.scene)
  );

  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    setSceneDraft(normalizeScene(thread.scene));
  }, [thread.thread_id, thread.scene]);

  const selectedKeys = new Set(
    sceneDraft.fields
      .map(field => field.key)
      .filter(Boolean)
  );

  const availableFieldOptions = SCENE_FIELD_OPTIONS.filter(opt => {
    if (opt.nsfwOnly && !sceneDraft.nsfw) return false;
    return !selectedKeys.has(opt.key);
  });

  const updateSceneDraft = patch => {
    setSceneDraft(prev => ({
      ...prev,
      ...patch,
    }));
  };

  const updateField = (fieldId, patch) => {
    setSceneDraft(prev => ({
      ...prev,
      fields: prev.fields.map(field =>
        field.id === fieldId ? { ...field, ...patch } : field
      ),
    }));
  };

  const addField = key => {
    if (!key) return;

    setSceneDraft(prev => {
      if (prev.fields.some(field => field.key === key)) return prev;

      return {
        ...prev,
        fields: [
          ...prev.fields,
          {
            id: makeFieldId(),
            key,
            value: "",
          },
        ],
      };
    });
  };

  const removeField = fieldId => {
    setSceneDraft(prev => ({
      ...prev,
      fields: prev.fields.filter(field => field.id !== fieldId),
    }));
  };

  const moveField = (fieldId, direction) => {
    setSceneDraft(prev => {
      const idx = prev.fields.findIndex(field => field.id === fieldId);
      if (idx === -1) return prev;

      const nextIdx = idx + direction;
      if (nextIdx < 0 || nextIdx >= prev.fields.length) return prev;

      const fields = [...prev.fields];
      const [field] = fields.splice(idx, 1);
      fields.splice(nextIdx, 0, field);

      return {
        ...prev,
        fields,
      };
    });
  };

  const handleSave = async () => {


    setSaving(true);
    setError("");

    try {
      const cleanedScene = {
        premise: sceneDraft.premise || "",
        nsfw: Boolean(sceneDraft.nsfw),
        status: sceneDraft.status || "active",
        fields: sceneDraft.fields
          .filter(field => field.key)
          .map(field => ({
            id: field.id || makeFieldId(),
            key: field.key,
            value: field.value || "",
          })),
        instructions: sceneDraft.instructions ?? null,
      };


      const patch = {
        guidance: guidanceDraft.trim() || null,
      };

      if (isScene) {
        patch.scene = cleanedScene;
      }

      const updated = await updateThread(thread.thread_id, patch);
      upsertThreadInState(setThreads, updated);


      // Optional: only if you distrust the returned payload or want to refresh ordering/filtering.
      // await fetchThreads?.();

      onClose();
    } catch (err) {
      console.error("Failed to update scene setup:", err);
      setError(err.message || "Failed to update scene setup.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-2xl rounded-lg border border-neutral-700 bg-neutral-950 p-4 shadow-xl">
        <div className="flex items-center justify-between border-b border-neutral-800 pb-2">
          <div>
            <div className="text-lg font-semibold text-neutral-100">
              {thread.title || "(untitled scene)"}
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="text-neutral-400 hover:text-neutral-100"
          >
            ×
          </button>
        </div>

        <div className="mt-3 space-y-3">
          {isScene ? (
            <>
              <div className="rounded border border-purple-500/30 bg-purple-950/20 p-3">

                <label className="mt-3 block">
                  <div className="mb-1 text-sm font-medium text-neutral-300">
                    Premise
                  </div>
                  <textarea
                    value={sceneDraft.premise}
                    onChange={e => updateSceneDraft({ premise: e.target.value })}
                    rows={4}
                    className="w-full rounded border border-neutral-700 bg-neutral-900 p-2 text-sm text-neutral-100 outline-none focus:border-purple-500"
                    placeholder="What is this scene? What room are we entering?"
                  />
                </label>

                <div className="mt-3 flex flex-wrap items-center gap-4">
                  <label className="flex items-center gap-2 text-sm text-neutral-300">
                    <input
                      type="checkbox"
                      checked={sceneDraft.nsfw}
                      onChange={e => updateSceneDraft({ nsfw: e.target.checked })}
                      className="accent-purple-500"
                    />
                    NSFW / adult scene
                  </label>

                  <label className="flex items-center gap-2 text-sm text-neutral-300">
                    <span className="text-xs text-neutral-400">Status</span>
                    <select
                      value={sceneDraft.status}
                      onChange={e => updateSceneDraft({ status: e.target.value })}
                      className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm text-neutral-100 outline-none focus:border-purple-500"
                    >
                      {SCENE_STATUS_OPTIONS.map(opt => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </div>

              <div className="rounded border border-neutral-800 bg-neutral-900/60 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-neutral-300">
                      Scene Fields
                    </div>
                    <div className="mt-1 text-xs text-neutral-500">
                      Optional structured context for the scene.
                    </div>
                  </div>

                  <select
                    value=""
                    onChange={e => {
                      addField(e.target.value);
                      e.target.value = "";
                    }}
                    className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-100 outline-none focus:border-purple-500"
                  >
                    <option value="">Add field…</option>
                    {availableFieldOptions.map(opt => (
                      <option key={opt.key} value={opt.key}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="mt-3 space-y-3">
                  {sceneDraft.fields.length === 0 ? (
                    <div className="rounded border border-dashed border-neutral-700 p-3 text-xs text-neutral-500">
                      No extra scene fields yet. Add only what this scene actually needs.
                    </div>
                  ) : (
                    sceneDraft.fields.map((field, idx) => (
                      <div
                        key={field.id}
                        className="rounded border border-neutral-800 bg-neutral-950 p-2"
                      >
                        <div className="mb-2 flex items-center justify-between gap-2">
                          <div className="text-xs font-semibold text-neutral-300">
                            {getSceneFieldLabel(field.key)}
                          </div>

                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              onClick={() => moveField(field.id, -1)}
                              disabled={idx === 0}
                              className="rounded px-2 py-1 text-xs text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100 disabled:opacity-30"
                            >
                              ↑
                            </button>

                            <button
                              type="button"
                              onClick={() => moveField(field.id, 1)}
                              disabled={idx === sceneDraft.fields.length - 1}
                              className="rounded px-2 py-1 text-xs text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100 disabled:opacity-30"
                            >
                              ↓
                            </button>

                            <button
                              type="button"
                              onClick={() => removeField(field.id)}
                              className="rounded px-2 py-1 text-xs text-red-300 hover:bg-red-950/40 hover:text-red-200"
                            >
                              Remove
                            </button>
                          </div>
                        </div>

                        <textarea
                          value={field.value || ""}
                          onChange={e =>
                            updateField(field.id, { value: e.target.value })
                          }
                          rows={3}
                          className="w-full rounded border border-neutral-700 bg-neutral-900 p-2 text-sm text-neutral-100 outline-none focus:border-purple-500"
                          placeholder={`Enter ${getSceneFieldLabel(field.key).toLowerCase()}...`}
                        />
                      </div>
                    ))
                  )}
                </div>
              </div>

              {error && (
                <div className="rounded border border-red-500/30 bg-red-950/30 p-2 text-xs text-red-200">
                  {error}
                </div>
              )}


            </>
          ) : (
            <div className="text-xs text-neutral-500">
              <label className="block">
                <div className="mb-1 text-sm font-medium text-neutral-300">
                  Thread Guidance
                </div>
                <div className="mb-1 text-xs text-neutral-500">
                  Persistent purpose, assumptions, or working agreements for this thread.
                </div>
                <textarea
                  value={guidanceDraft}
                  onChange={e => setGuidanceDraft(e.target.value)}
                  rows={5}
                  placeholder="What is this room for? How should your muse treat information and respond here?"
                  className="w-full rounded border border-neutral-700 bg-neutral-900 p-2 text-sm text-neutral-100 outline-none focus:border-purple-500"
                />
              </label>
            </div>
          )}
            <div className="flex justify-end gap-2 border-t border-neutral-800 pt-3">
              <button
                type="button"
                onClick={onClose}
                disabled={saving}
                className="rounded border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-800 disabled:opacity-50"
              >
                Cancel
              </button>

              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="rounded bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-500 disabled:opacity-50"
              >
                {saving ? "Saving…" : "Save Setup"}
              </button>
            </div>
        </div>
      </div>
    </div>
  );
}