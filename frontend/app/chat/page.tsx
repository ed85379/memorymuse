// app/chat/page.tsx
// ChatPage layout:
// 1) General controls
// 2) UI initial load
// 3) Projects & threads
// 4) Message actions
// 5) Websocket
// 6) Tool panel / files
// 7) Rendering (tabs + layout)
"use client";
import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { nanoid } from "nanoid";
// Hooks
import { useConfig } from '@/hooks/ConfigContext';
import { useFeatures } from '@/hooks/FeaturesContext';
import { useAudioControls } from "@/hooks/useAudioControls";
// Components
import ChatTab from './ChatTab';
import HistoryTab from './HistoryTab';
import PresencePanel from './PresencePanel';
import MotdBar from './MotdBar';
import TabbedToolPanel from './TabbedToolPanel';
import ThreadManagerPanel from '@/components/app/ThreadManagerPanel';
import SettingsPanel from '@/components/app/SettingsPanel';
import RemindersPanel from '@/components/app/RemindersPanel';
import RecycleBin from './RecycleBin';
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
// Utils
import { trimMessages } from '@/utils/utils';
import { createThreadWithMessages, clearOpenThread, setThreadHidden } from '@/utils/threadActions.js'
import { updateNavState, updateThreadsState } from "@/utils/statesFunctions";
import {
  addToThread,
  removeFromThread,
  handleMultiAction,
   } from "@/utils/messageActions";
 // Icons
import { Split, CircleX, Settings, BellRing, BrushCleaning } from "lucide-react";

// General props
const TABS = [
  { key: "chat", label: "Chat" },
  { key: "history", label: "History" },
  { key: "thread", label: "Thread" },
  ];

export default function ChatPage() {
  // General controls
  const [activeTab, setActiveTab] = useState("chat");
  const [messages, setMessages] = useState([]);
  const [threadMessages, setThreadMessages] = useState([]);
  const [connecting, setConnecting] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [scrollToMessageId, setScrollToMessageId] = useState(null);

  // ------------------------------------
  // UI States Initial Load
  // ------------------------------------
  const { uiStates, loading: uiStatesLoading, userConfig } = useConfig();
  const enableMOTD = userConfig?.muse_features?.ENABLE_MOTD || false;
  const enableReminders = userConfig?.muse_features?.ENABLE_REMINDERS || false;
  const initialMotd = uiStates?.motd?.text ?? "";
  const [motd, setMotd] = useState(initialMotd);
  const [status, setStatus] = useState([]);
  const initialProjectId = uiStates?.projects?.project_id ?? "";
  const [timeSkipOverride, setTimeSkipOverride] = useState(null);
  const timeSkipActive =
  timeSkipOverride !== null
    ? timeSkipOverride
    : Boolean(uiStates?.time_skip?.active);
  const { adminConfig, adminLoading } = useFeatures();
  const mm = adminConfig?.mm_features || {};
  const enableTTS = !!mm.ENABLE_TTS;
  const enablePublic = !!mm.ENABLE_PUBLIC_INTERFACES;
  const enableSync = !!mm.ENABLE_SYNC;

  useEffect(() => {
    if (!uiStatesLoading) {
      if (uiStates?.nav?.main_tab) {
        setActiveTab(uiStates.nav.main_tab);
      }
    }
  }, [uiStatesLoading, uiStates]);

  useEffect(() => {
    if (!uiStatesLoading) {
      const text = uiStates?.motd?.text ?? "";
      setMotd(text);
    }
  }, [uiStatesLoading, uiStates]);

  // Hydrate from uiStates once they’re available
  useEffect(() => {
    if (!uiStatesLoading && uiStates) {
      // 1) Selected project id (cursor)
      const currentProjectId = uiStates.projects.project_id ?? "";
      setSelectedProjectId(currentProjectId);
      const perProject = uiStates.projects.per_project ?? {};
      const globalPrefs = uiStates.projects.default_project_settings ?? {};

      // 2) Focus / blend ratio
      const projectPrefs = currentProjectId? perProject[currentProjectId] ?? {} : {};
      const blend =
        typeof projectPrefs.blend_ratio === "number"
          ? projectPrefs.blend_ratio
          : typeof globalPrefs.blend_ratio === "number"
          ? globalPrefs.blend_ratio
          : 0.5;
      setFocus(blend);

      // 3) Auto-assign
      const auto =
        typeof projectPrefs.auto_assign === "boolean"
          ? projectPrefs.auto_assign
          : typeof globalPrefs.auto_assign === "boolean"
          ? globalPrefs.auto_assign
          : true;
      setAutoAssign(auto);
    }
  }, [uiStatesLoading, uiStates]);
  // ------------------------------------
  // End - UI States Initial Load
  // ------------------------------------

  // ------------------------------------
  // Projects, Threads, Assets States and Functions
  // ------------------------------------
  const [projects, setProjects] = useState([]);
  const [projectMap, setProjectMap] = useState({});
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [threads, setThreads] = useState([]);
  const [threadMap, setThreadMap] = useState({});
  const initialOpenThreadId = uiStates?.threads?.open_thread_id ?? "";
  const [openThreadId, setOpenThreadId] = useState(initialOpenThreadId);
  const [threadManagerOpen, setThreadManagerOpen] = useState(false)
  const [assets, setAssets] = useState([]);
  const [assetsLoading, setAssetsLoading] = useState(true);
  const [assetsRefreshing, setAssetsRefreshing] = useState(true);
  const [assetsError, setAssetsError] = useState(null);

  const fetchProjects = async () => {
    const res = await fetch("/api/projects");
    const data = await res.json();
    setProjects(data.projects || []);
    setProjectsLoading(false);
    // Build a file map for quick lookups
    const files = {};
    for (const proj of data.projects || []) {
      for (const fid of (proj.file_ids || [])) {
        if (!files[fid]) files[fid] = { name: fid }; // You would actually want to fetch file metadata
      }
    }
    setProjectMap({ projects: Object.fromEntries((data.projects || []).map(p => [p._id, p])), files });
  };
  useEffect(() => { fetchProjects(); }, []);

  const fetchAssets = useCallback(async ({ quiet = false } = {}) => {
    if (quiet) {
      setAssetsRefreshing(true);
    } else {
      setAssetsLoading(true);
    }
    setAssetsError(null);

    try {
      const res = await fetch(`/api/assets/?lifecycle_status=available&limit=200`);

      if (!res.ok) {
        throw new Error(`Failed to load assets: HTTP ${res.status}`);
      }

      const data = await res.json();

      // Be forgiving while the API shape evolves.
      setAssets(data.assets || data.items || data.results || []);
    } catch (e) {
      console.error(e);
      setAssetsError(e.message || "Failed to load assets.");
      setAssets([]);
    } finally {
      setAssetsLoading(false);
      setAssetsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchAssets();
  }, [fetchAssets]);

  const assetsByProjectId = useMemo(() => {
    const map = {};

    for (const asset of assets || []) {
      const assetId = asset.asset_id || asset._id;

      for (const projectId of asset.project_ids || []) {
        if (!map[projectId]) map[projectId] = [];

        map[projectId].push({
          id: assetId,
          name:
            asset.display_name ||
            asset.filename ||
            asset.name ||
            asset.original_filename ||
            assetId,
          size: asset.size_bytes || asset.size,
          source_type: asset.source_type,
          asset,
        });
      }
    }

    return map;
  }, [assets]);

  const assetsById = useMemo(() => {
    const map = {};

    for (const asset of assets || []) {
      const assetId = asset.asset_id || asset._id;
      if (!assetId) continue;

      map[assetId] = asset;
    }

    return map;
  }, [assets]);

  const fetchThreads = async () => {
    const res = await fetch("/api/threads/");
    const data = await res.json();
    setThreads(data.threads || []);
    setThreadMap({ threads: Object.fromEntries((data.threads || []).map(t => [t.thread_id, t]))});
  };
  useEffect(() => { fetchThreads(); }, []);

  useEffect(() => {
    if (!uiStatesLoading) {
      if (uiStates?.threads?.open_thread_id) {
        setOpenThreadId(uiStates.threads.open_thread_id);
      }
    }
  }, [uiStatesLoading, uiStates]);




  const visibleTabs = TABS.filter(tab =>
    tab.key === "thread" ? !!openThreadId: true
  );
  const openThread = threads.find(thread => thread.thread_id === openThreadId);
  const openThreadTitle = openThread?.title ?? 'Thread';
  const closedThreadTitle = "Threads & Scenes";


  // ------------------------------------
  // End - Projects and Threads States and Functions
  // ------------------------------------


  // ------------------------------------
  // Message Actions States and Functions
  // ------------------------------------
  const [tagDialogOpen, setTagDialogOpen] = useState(null);
  const [showProjectPanel, setShowProjectPanel] = useState(false);
  const [showTagPanel, setShowTagPanel] = useState(null);
  const [showThreadPanel, setShowThreadPanel] = useState(null);
  const [showSingleThreadPanel, setShowSingleThreadPanel] = useState(null);
  const [multiSelectEnabled, setMultiSelectEnabled] = useState(false);
  const [selectedMessageIds, setSelectedMessageIds] = useState([]);
  const clearSelectionAndExit = () => {
    setSelectedMessageIds([]);
    setMultiSelectEnabled(false);
  };

  const handleToggleMultiSelect = (enabled) => {
    setMultiSelectEnabled(enabled);
    if (!enabled) {
      setSelectedMessageIds([]);
    }
  };

  const onMultiAction = (action, options = {}) => {
    console.log("onMultiAction called with:", action);
    switch (action) {
      case "set_project":
        console.log(">>> setting showProjectPanel = true");
        setShowProjectPanel(true);
        break;
      case "add_tags":
        console.log(">>> setting showTagPanel = 'add'");
        setShowTagPanel("add");
        break;
      case "remove_tags":
        console.log(">>> setting showTagPanel = 'remove'");
        setShowTagPanel("remove");
        break;
      case "add_threads":
        console.log(">>> setting showThreadPanel = 'add'");
        setShowThreadPanel("add");
        break;
      case "remove_threads":
        console.log(">>> setting showThreadPanel = 'remove'");
        setShowThreadPanel("remove");
        break;
      default:
        // simple actions go straight through
        handleMultiAction(setMessages, setThreadMessages, null, selectedMessageIds, action, options);
        clearSelectionAndExit();
    }
  };

  const handleToggleSelect = useCallback((message_id) => {
    setSelectedMessageIds((prev) =>
      prev.includes(message_id)
        ? prev.filter((id) => id !== message_id)
        : [...prev, message_id]
    );
  }, [setSelectedMessageIds]);

  const handleConfirmProject = (project_id) => {
    setShowProjectPanel(false);
    handleMultiAction(setMessages, setThreadMessages, null, selectedMessageIds, "set_project", {
      project_id,
    });
    clearSelectionAndExit();
  };

  const handleConfirmTagsAdd = (tagsToAdd) => {
    setShowTagPanel(null);
    handleMultiAction(setMessages, setThreadMessages, null, selectedMessageIds, "add_tags", {
      tagsToAdd,
    });
    clearSelectionAndExit();
  };

  const handleConfirmTagsRemove = (tagsToRemove) => {
    setShowTagPanel(null);
    handleMultiAction(setMessages, setThreadMessages, null, selectedMessageIds, "remove_tags", {
      tagsToRemove,
    });
    clearSelectionAndExit();
  };

  const handleConfirmThreadJoin = (thread_id) => {
    setShowThreadPanel(null);
    handleMultiAction(setMessages, setThreadMessages, null, selectedMessageIds, "add_threads");
    clearSelectionAndExit();
  };

  const handleConfirmThreadRemove = (thread_id) => {
    setShowThreadPanel(null);
    handleMultiAction(setMessages, setThreadMessages, null, selectedMessageIds, "remove_threads");
    clearSelectionAndExit();
  };

  const handleConfirmThreadCreate = () => {
    setShowThreadPanel(null);
    handleMultiAction(setMessages, setThreadMessages, null, selectedMessageIds, "add_threads");
    clearSelectionAndExit();
  };

  const existingTagsForSelection = useMemo(() => {
    if (!selectedMessageIds.length) return [];

    const tagSet = new Set();

    messages.forEach((msg) => {
      if (!selectedMessageIds.includes(msg.message_id)) return;
      (msg.user_tags || []).forEach((tag) => tagSet.add(tag));
    });

    return Array.from(tagSet).sort();
  }, [messages, selectedMessageIds]);

  const existingThreadsForSelection = useMemo(() => {
    if (!selectedMessageIds.length) return [];

    const threadSet = new Set();

    messages.forEach((msg) => {
      if (!selectedMessageIds.includes(msg.message_id)) return;
      (msg.thread_ids || []).forEach((thread_id) => threadSet.add(thread_id));
    });

    return Array.from(threadSet).sort();
  }, [messages, selectedMessageIds]);

  const handleReturnToThisMoment = async (message_id: string) => {
    const res = await fetch(`/api/time_skip/${message_id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });

    if (!res.ok) {
      console.error("Failed to set time skip");
      return;
    }

    const data = await res.json(); // { time_skip: {...} }


    setTimeSkipOverride(true);
    setActiveTab("chat");
  };


  const handleCreateThread = (msg_ids, title) => {
    createThreadWithMessages({
      setMessages,
      setThreadMessages,
      setAltMessages: null,
      selectedMessageIds: msg_ids,
      setOpenThreadId,
      setActiveTab,
      updateThreadsState,
      fetchThreads,
      title,
      setThreads,
    });
    setShowSingleThreadPanel(false);
    setShowThreadPanel(false);
  };

  const handleJoinThread = (msg, threadId) => {
    addToThread(setMessages, setThreadMessages, null, msg, threadId);
    console.log("MainJoin", msg);
    // you might or might not want to auto-open the thread tab here
    setShowSingleThreadPanel(false);
    setShowThreadPanel(false);
  };

  const handleLeaveThread = (msg, threadId) => {
    removeFromThread(setMessages, setThreadMessages, null, msg, threadId);
    setShowSingleThreadPanel(false);
    setShowThreadPanel(false);
  };
  // ------------------------------------
  // End - Message Actions States and Functions
  // ------------------------------------

  // ------------------------------------
  // Websocket States and Functions
  // ------------------------------------
  const audioControls = useAudioControls();
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const ACTIVE_WINDOW_LIMIT = 10;

  function upsertMessage(existing, incoming) {
    const index = existing.findIndex(m => m.message_id === incoming.message_id);
    if (index === -1) {
      return [...existing, incoming];
    } else {
      const copy = existing.slice();
      copy[index] = { ...copy[index], ...incoming };
      return copy;
    }
  }

  useEffect(() => {
    let cancelled = false;

    function connectWebSocket() {
      setConnecting(true);
      const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
      const wsHost = window.location.host;
      const wsPath = "/ws";
      const ws = new WebSocket(`${wsProtocol}://${wsHost}${wsPath}`);
      wsRef.current = ws;

      const tryRegister = () => {
        if (ws.readyState === 1) {
          ws.send(JSON.stringify({ listen_as: "webui" }));
          setConnecting(false);
        } else if (!cancelled) {
          setTimeout(tryRegister, 50);
        }
      };
      tryRegister();

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        switch (data.type) {
          case "muse_message": {
            const text = data.message;
            const role = data.role;
            const message_id = data.message_id;
            const project_id = data.project_id;
            const thread_id = data.thread_id;
            const timestamp = data.timestamp;
            const metadata = data.metadata;

            const incoming = {
              role,
              text,
              message_id,
              timestamp,
              project_id,
              thread_ids: thread_id ? [thread_id] : [],
              metadata
            };

            setMessages(prev => {
              const updated = trimMessages(
                upsertMessage(prev, incoming),
                ACTIVE_WINDOW_LIMIT
              );
              setScrollToMessageId(message_id);
              return updated;
            });

            if (thread_id) {
              setThreadMessages(prev => {
                const updated = trimMessages(
                  upsertMessage(prev, incoming),
                  ACTIVE_WINDOW_LIMIT
                );
                return updated;
              });
            }

            setThinking(false);
            if (data.type === "muse_message") {
              const incoming = data.message;
              if (audioControls.audioResponseRef.current) {
                audioControls.audioResponseRef.current(incoming);
              }
            }
            break;
          }

          case "user_message": {
            const text = data.message;
            const role = data.role;
            const message_id = data.message_id;
            const project_id = data.project_id;
            const thread_id = data.thread_id;
            const timestamp = data.timestamp;
            const metadata = data.metadata;

            const incoming = {
              role,
              text,
              message_id,
              timestamp,
              project_id,
              thread_ids: thread_id ? [thread_id] : [],
              metadata,
            };

            setMessages(prev => {
              const updated = trimMessages(
                upsertMessage(prev, incoming),
                ACTIVE_WINDOW_LIMIT
              );

              return updated;
            });

            if (thread_id) {
              setThreadMessages(prev => {
                const updated = trimMessages(
                  upsertMessage(prev, incoming),
                  ACTIVE_WINDOW_LIMIT
                );
                return updated;
              });
            }

            break;
          }

          case "motd_update": {
            setMotd(data.message);
            break;
          }

          case "status_message": {
            console.log("APPENDING STATUS:", data.message);
            setStatus(prev => {
              const next = [...prev, data.message];
              console.log("NEXT STATUS:", next);
              return next;
            });
            break;
          }

          // later:
          // case "avatar_update":
          //   setAvatarUrl(data.message);
          //   break;

          default:
            // ignore unknown types for now
            break;
        }
      };

      ws.onclose = () => {
        if (!cancelled) {
          setConnecting(true);
          reconnectTimeoutRef.current = setTimeout(connectWebSocket, 1500);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connectWebSocket();

    return () => {
      cancelled = true;
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    };
  }, []); // single socket for the page

  // ------------------------------------
  // End - Websocket States and Functions
  // ------------------------------------

  // ------------------------------------
  // Tool Panel / Files States and Functions
  // ------------------------------------
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [project, setProject] = useState(null);
  const [focus, setFocus] = useState(0.5);
  const [autoAssign, setAutoAssign] = useState(false);
  const [injectedFiles, setInjectedFiles] = useState([]);
  const [injectedAssets, setInjectedAssets] = useState([]);

  // Ephemeral file controls
  const [ephemeralFiles, setEphemeralFiles] = useState([]);
  const [editingEphemeralId, setEditingEphemeralId] = useState(null);
  const [ephemeralNameDraft, setEphemeralNameDraft] = useState("");
  const [files, setFiles] = useState([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [filesError, setFilesError] = useState(null);

  // On project select: fetch project doc (read-only)
  useEffect(() => {
    if (!selectedProjectId) {
      setProject(null);

      setInjectedFiles([]);
      setInjectedAssets([]);
      return;
    }
    // 1. Load project metadata
    fetch(`/api/projects/${selectedProjectId}`)
      .then(res => res.json())
      .then(data => {
        setProject(data.project || data);

        setInjectedFiles([]);
        setInjectedAssets([]);
      });

    // 2. Load effective UI state for this project
    fetch(`/api/states/${selectedProjectId}`)
      .then(res => res.json())
      .then(state => {
        if (typeof state.auto_assign === "boolean") {
          setAutoAssign(state.auto_assign);
        }
        if (typeof state.blend_ratio === "number") {
          setFocus(state.blend_ratio);
        }
      });

  }, [selectedProjectId]);

  // Fetch files for this project (special endpoint)
  const fetchFiles = useCallback(() => {
    if (!selectedProjectId) {
      setFiles([]);
      setFilesLoading(false);
      setFilesError(null);
      return;
    }
    setFilesLoading(true);
    setFilesError(null);
    fetch(`/api/projects/${selectedProjectId}/files`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(data => {
        const files = (data.files || []).map(f => ({
          id: f._id,
          name: f.filename || f.name || "",
          mimetype: f.mimetype || "application/octet-stream",
          size: f.size || 0,
          caption: f.caption || "",
          uploaded_on: f.uploaded_on || "",
          description: f.description || "",
          tags: f.tags || [],
        }));
        setFiles(files);
        setFilesLoading(false);
      })
      .catch(() => {
        setFilesError("Failed to load files.");
        setFiles([]);
        setFilesLoading(false);
      });
  }, [selectedProjectId]);

  // Refetch files whenever project changes
  useEffect(() => {
    fetchFiles();
  }, [fetchFiles]);

  const handlePinToggle = fid => {
    setInjectedFiles(prev =>
      prev.map(f =>
        f.id === fid ? { ...f, pinned: !f.pinned } : f
      )
    );
  };
  const handleAssetPinToggle = aid => {
    setInjectedAssets(prev =>
      prev.map(a =>
        a.id === aid ? { ...a, pinned: !a.pinned } : a
      )
    );
  };

  const handleEphemeralUpload = (file) => {
    if (!file) return;
    // Optional: check for duplicates or size/type limits here
    setEphemeralFiles(prev => [
      ...prev,
      {
        file, // Store the File object itself
        name: file.name,
        type: file.type,
        size: file.size,
        id: crypto.randomUUID(), // For UI tracking/removal
        // You could add preview data URLs for images if you want
      }
    ]);
  };

  const handleEphemeralRename = (id, rawName) => {
    const name = rawName.trim();

    if (!name) return;

    setEphemeralFiles(prev =>
      prev.map(file =>
        file.id === id
          ? { ...file, name }
          : file
      )
    );
  };

  const [showRecycleBin, setShowRecycleBin] = useState(false);
  const handleShowRecycleBin = () => {
    setShowRecycleBin((prev) => !prev);
  };

  // ------------------------------------
  // End - Tool Panel / Files States and Functions
  // ------------------------------------

  return (
    <div className="flex flex-col h-full w-full min-h-0">
      {/* Sub-tab selector */}
        <div className="flex gap-2 border-b border-neutral-800 px-6">
          {TABS.map(tab => {
            const isThread = tab.key === "thread";
            const isActive = activeTab === tab.key;
            const hasOpenThread = !!openThreadId;

            const baseLabel = isThread
              ? openThreadId
                ? openThreadTitle || "Active thread"
                : closedThreadTitle
              : tab.label;

            const handleTabClick = () => {
              if (isThread) {
                if (hasOpenThread) {
                  // normal behavior: go to thread view
                  setActiveTab("thread");
                  updateNavState({ main_tab: "thread" });
                } else {
                  // no active thread: just open the manager
                  if (threadManagerOpen) {
                    setThreadManagerOpen(false);
                  } else {
                    setThreadManagerOpen(true);
                  }
                }
              } else {
                // non-thread tab
                setActiveTab(tab.key);
                updateNavState({ main_tab: tab.key });
              }
            };

            return (
              <div
                key={tab.key}
                className={`
                  flex items-center
                  px-4 py-2 rounded-t-lg border-b-2 transition-all
                  ${isActive
                    ? "border-purple-400 text-purple-200 font-bold bg-neutral-900"
                    : "border-transparent text-purple-400 hover:bg-neutral-900/50"
                  }
                `}
              >
                {/* Main tab button: label + (optional) Split icon */}
                <button
                  type="button"
                  onClick={handleTabClick}
                  title={
                    tab.key === "history"
                      ? "View, search, and filter conversation logs"
                      : isThread && openThreadId
                      ? "View this thread"
                      : isThread
                      ? "Select or manage threads"
                      : ""
                  }
                  className="inline-flex items-center gap-1 align-middle"
                >
                  {isThread && (
                    <Split className="w-4 h-4 translate-y-[1px]" />
                  )}

                  <span className="leading-none">
                    {baseLabel}
                  </span>
                </button>

                {/* Close icon, only when a thread is active */}
                {isThread && openThreadId && (
                  <button
                    type="button"
                    onClick={() =>
                      clearOpenThread({
                        setOpenThreadId,
                        setActiveTab,
                        updateThreadsState,
                      })
                    }
                    className="ml-1 text-neutral-500 hover:text-neutral-200"
                    title="Close thread"
                  >
                    <CircleX className="w-3 h-3" />
                  </button>
                )}

                {/* Manager dropdown trigger: always present for thread tab */}
                {isThread && (
                  <button
                    type="button"
                    onClick={() => {
                      // however you currently toggle the manager
                      if (threadManagerOpen) {
                        setThreadManagerOpen(false);
                      } else {
                        setThreadManagerOpen(true);
                      }
                      // optional: ensure we're on the thread tab when manager opens
                      //setActiveTab("thread");
                      //updateNavState({ main_tab: "thread" });
                    }}
                    className="ml-1 text-xs text-neutral-400 hover:text-neutral-100"
                    title="Open thread manager"
                  >
                    <Settings className="w-4 h-4 translate-y-[1px]" />
                  </button>
                )}
              </div>
            );
          })}



          <div className="ml-auto">
            <span style={{ padding: 10}}>
              <Sheet>
                <SheetTrigger asChild>
                  <button className="inline-flex items-center gap-1 text-xs text-neutral-300 hover:text-white">
                    <BrushCleaning className="w-3 h-3" />
                    <span>Forgotten Messages</span>
                  </button>
                </SheetTrigger>
                  <SheetContent
                    side="right" size="wide"
                    className="bg-neutral-900 border-l border-neutral-700"
                  >
                  <SheetHeader>
                    <SheetDescription className="sr-only">
                      Forgotten Messages
                    </SheetDescription>
                  </SheetHeader>
                  <div className="flex items-center justify-between mb-4">
                    <SheetTitle className="text-sm font-semibold text-neutral-100">
                      Forgotten Messages
                    </SheetTitle>
                  </div>

                  <div className="space-y-3 overflow-y-auto max-h-[calc(100vh-6rem)] pr-1">
                    <RecycleBin
                      // Feature flags
                      enableTTS={enableTTS}
                      enablePublic={enablePublic}
                      enableSync={enableSync}
                      // General and nav
                      audioControls={audioControls}

                      // Project & Threads
                      threads={threads}
                      threadMap={threadMap}
                      projects={projects}
                      project={project}
                      fetchProjects={fetchProjects}
                      projectMap={projectMap}
                      projectsLoading={projectsLoading}

                      // Message Actions
                      threadMessages={threadMessages}
                      setThreadMessages={setThreadMessages}
                      setChatMessages={setMessages}
                      clearSelectionAndExit={clearSelectionAndExit}
                      onReturnToThisMoment={handleReturnToThisMoment}
                      createThreadWithMessages={createThreadWithMessages}
                      multiSelectEnabled={multiSelectEnabled}
                      selectedMessageIds={selectedMessageIds}
                      showProjectPanel={showProjectPanel}
                      setShowProjectPanel={setShowProjectPanel}
                      showTagPanel={showTagPanel}
                      setShowTagPanel={setShowTagPanel}
                      showThreadPanel={showThreadPanel}
                      setShowThreadPanel={setShowThreadPanel}
                      showSingleThreadPanel={showSingleThreadPanel}
                      setShowSingleThreadPanel={setShowSingleThreadPanel}
                      handleToggleMultiSelect={handleToggleMultiSelect}
                      handleToggleSelect={handleToggleSelect}
                      handleCreateThread={handleCreateThread}
                      handleJoinThread={handleJoinThread}
                      handleLeaveThread={handleLeaveThread}
                      tagDialogOpen={tagDialogOpen}
                      setTagDialogOpen={setTagDialogOpen}
                      handleConfirmProject={handleConfirmProject}
                      existingTagsForSelection={existingTagsForSelection}
                      existingThreadsForSelection={existingThreadsForSelection}
                      clearSelectionAndExit={clearSelectionAndExit}
                    />
                  </div>

                  <div className="mt-4 flex justify-end gap-2">
                  {/* Perhaps save/cancel button here if we don't use onBlur */}
                  </div>
                </SheetContent>
              </Sheet>
            </span>
            {enableReminders && (
            <span style={{ padding: 10}}>
              <Sheet>
                <SheetTrigger asChild>
                  <button className="inline-flex items-center gap-1 text-xs text-neutral-300 hover:text-white">
                    <BellRing className="w-3 h-3" />
                    <span>Reminders</span>
                  </button>
                </SheetTrigger>
                <SheetContent side="right" className="w-full sm:max-w-md bg-neutral-900 border-l border-neutral-700">
                  <SheetHeader>
                    <SheetDescription className="sr-only">
                      Reminders panel
                    </SheetDescription>
                  </SheetHeader>
                  <div className="flex items-center justify-between mb-4">
                    <SheetTitle className="text-sm font-semibold text-neutral-100">
                      Reminders
                    </SheetTitle>
                  </div>

                  <div className="space-y-3 overflow-y-auto max-h-[calc(100vh-6rem)] pr-1">
                    <RemindersPanel

                    />
                  </div>

                  <div className="mt-4 flex justify-end gap-2">
                  {/* Perhaps save/cancel button here if we don't use onBlur */}
                  </div>
                </SheetContent>
              </Sheet>
            </span>
            )}
            <span style={{ padding: 10}}>
              <Sheet>
                <SheetTrigger asChild>
                  <button className="inline-flex items-center gap-1 text-xs text-neutral-300 hover:text-white">
                    <Settings className="w-3 h-3" />
                    <span>Settings</span>
                  </button>
                </SheetTrigger>
                <SheetContent side="right" className="w-full sm:max-w-md bg-neutral-900 border-l border-neutral-700">
                  <SheetHeader>
                    <SheetDescription className="sr-only">
                      User configuration panel
                    </SheetDescription>
                  </SheetHeader>
                  <div className="flex items-center justify-between mb-4">
                    <SheetTitle className="text-sm font-semibold text-neutral-100">
                      Settings
                    </SheetTitle>
                  </div>

                  <div className="space-y-3 overflow-y-auto max-h-[calc(100vh-6rem)] pr-1">
                    <SettingsPanel
                      audioControls={audioControls}
                    />
                  </div>

                  <div className="mt-4 flex justify-end gap-2">
                  {/* Perhaps save/cancel button here if we don't use onBlur */}
                  </div>
                </SheetContent>
              </Sheet>
            </span>
          </div>
        </div>
        {threadManagerOpen && (
        <div className="absolute left-52 top-28 mt-0 z-20 flex justify-end">
          <ThreadManagerPanel
            threads={threads}
            setThreads={setThreads}
            fetchThreads={fetchThreads}
            setMessages={setMessages}
            setThreadMessages={setThreadMessages}
            setThreadManagerOpen={setThreadManagerOpen}
            openThreadId={openThreadId}
            setOpenThreadId={setOpenThreadId}
            setActiveTab={setActiveTab}
            updateThreadsState={updateThreadsState}
          />
        </div>
        )}
      {/* Sub-tab content */}
      {activeTab === "chat" && (
        <div className="relative grid grid-cols-1 md:grid-cols-3 gap-6 flex-1 min-h-0 px-6">
          <div className=" relative md:col-span-2 overflow-y-auto">
            <ChatTab
              // Feature flags
              enableTTS={enableTTS}
              // General and nav
              audioControls={audioControls}
              ephemeralFiles={ephemeralFiles}
              setEphemeralFiles={setEphemeralFiles}
              editingEphemeralId={editingEphemeralId}
              setEditingEphemeralId={setEditingEphemeralId}
              ephemeralNameDraft={ephemeralNameDraft}
              setEphemeralNameDraft={setEphemeralNameDraft}
              handleEphemeralUpload={handleEphemeralUpload}
              handleEphemeralRename={handleEphemeralRename}
              messages={messages}
              setMessages={setMessages}
              threadMessages={threadMessages}
              setThreadMessages={setThreadMessages}
              setAltMessages={null}
              wsRef={wsRef}
              connecting={connecting}
              thinking={thinking}
              setThinking={setThinking}
              scrollToMessageId={scrollToMessageId}
              setScrollToMessageId={setScrollToMessageId}
              ACTIVE_WINDOW_LIMIT={ACTIVE_WINDOW_LIMIT}
              timeSkipOverride={timeSkipOverride}
              setTimeSkipOverride={setTimeSkipOverride}
              timeSkipActive={timeSkipActive}

              // Project & Threads
              threads={threads}
              threadMap={threadMap}
              projects={projects}
              project={project}
              projectMap={projectMap}
              projectsLoading={projectsLoading}
              selectedProjectId={selectedProjectId}
              focus={focus}
              autoAssign={autoAssign}
              injectedFiles={injectedFiles}
              files={files}
              assetsByProjectId={assetsByProjectId}
              assetsById={assetsById}
              setInjectedFiles={setInjectedFiles}
              injectedAssets={injectedAssets}
              setInjectedAssets={setInjectedAssets}
              handlePinToggle={handlePinToggle}
              handleAssetPinToggle={handleAssetPinToggle}
              onCreateThread={handleCreateThread}
              onJoinThread={handleJoinThread}
              onLeaveThread={handleLeaveThread}

              // Message Actions
              createThreadWithMessages={createThreadWithMessages}
              multiSelectEnabled={multiSelectEnabled}
              selectedMessageIds={selectedMessageIds}
              showProjectPanel={showProjectPanel}
              setShowProjectPanel={setShowProjectPanel}
              showTagPanel={showTagPanel}
              setShowTagPanel={setShowTagPanel}
              showThreadPanel={showThreadPanel}
              setShowThreadPanel={setShowThreadPanel}
              showSingleThreadPanel={showSingleThreadPanel}
              setShowSingleThreadPanel={setShowSingleThreadPanel}
              handleToggleMultiSelect={handleToggleMultiSelect}
              handleToggleSelect={handleToggleSelect}
              onMultiAction={onMultiAction}
              handleCreateThread={handleCreateThread}
              handleJoinThread={handleJoinThread}
              handleLeaveThread={handleLeaveThread}
              tagDialogOpen={tagDialogOpen}
              setTagDialogOpen={setTagDialogOpen}
              handleConfirmProject={handleConfirmProject}
              handleConfirmTagsAdd={handleConfirmTagsAdd}
              handleConfirmTagsRemove={handleConfirmTagsRemove}
              existingTagsForSelection={existingTagsForSelection}
              existingThreadsForSelection={existingThreadsForSelection}
              clearSelectionAndExit={clearSelectionAndExit}
              status={status}
              setStatus={setStatus}
            />
          </div>
          <div className="hidden md:flex flex-col w-full md:max-w-sm sticky top-6 self-start h-[80vh] min-h-[400px]">
            {/* Expandable/collapsible presence panel */}
            <PresencePanel speaking={audioControls.speaking} />
            {enableMOTD && (
              <MotdBar motd={motd} />
            )}
            {/* Always-scrollable tool panel below */}
            <div className="flex-1 overflow-y-auto">
            <TabbedToolPanel
              threads={threads}
              threadMap={threadMap}
              projects={projects}
              project={project}
              fetchProjects={fetchProjects}
              projectMap={projectMap}
              selectedProjectId={selectedProjectId}
              setSelectedProjectId={setSelectedProjectId}
              assetsByProjectId={assetsByProjectId}
              assetsById={assetsById}
              assetsLoading={assetsLoading}
              fetchAssets={fetchAssets}
              focus={focus}
              setFocus={setFocus}
              autoAssign={autoAssign}
              setAutoAssign={setAutoAssign}
              injectedFiles={injectedFiles}
              setInjectedFiles={setInjectedFiles}
              injectedAssets={injectedAssets}
              setInjectedAssets={setInjectedAssets}
              fetchFiles={fetchFiles}
              files={files}
              setFiles={setFiles}
              filesLoading={filesLoading}
              setFilesLoading={setFilesLoading}
              filesError={filesError}
              handlePinToggle={handlePinToggle}
              handleAssetPinToggle={handleAssetPinToggle}
            />
            </div>
          </div>
        </div>
      )}

      {activeTab === "thread" && openThreadId && (
        <div className="relative grid grid-cols-1 md:grid-cols-3 gap-6 flex-1 min-h-0 px-6">
          <div className=" relative md:col-span-2 overflow-y-auto">
            <ChatTab
              // Feature flags
              enableTTS={enableTTS}
              // General and nav
              threadId={openThreadId}
              audioControls={audioControls}
              ephemeralFiles={ephemeralFiles}
              setEphemeralFiles={setEphemeralFiles}
              editingEphemeralId={editingEphemeralId}
              setEditingEphemeralId={setEditingEphemeralId}
              ephemeralNameDraft={ephemeralNameDraft}
              setEphemeralNameDraft={setEphemeralNameDraft}
              handleEphemeralUpload={handleEphemeralUpload}
              handleEphemeralRename={handleEphemeralRename}
              messages={messages}
              setMessages={setMessages}
              threadMessages={threadMessages}
              setThreadMessages={setThreadMessages}
              setAltMessages={null}
              wsRef={wsRef}
              connecting={connecting}
              thinking={thinking}
              setThinking={setThinking}
              scrollToMessageId={scrollToMessageId}
              setScrollToMessageId={setScrollToMessageId}
              ACTIVE_WINDOW_LIMIT={ACTIVE_WINDOW_LIMIT}
              timeSkipOverride={timeSkipOverride}
              setTimeSkipOverride={setTimeSkipOverride}
              timeSkipActive={timeSkipActive}

              // Project & Threads
              threads={threads}
              threadMap={threadMap}
              projects={projects}
              project={project}
              projectMap={projectMap}
              projectsLoading={projectsLoading}
              selectedProjectId={selectedProjectId}
              focus={focus}
              autoAssign={autoAssign}
              injectedFiles={injectedFiles}
              files={files}
              assetsByProjectId={assetsByProjectId}
              assetsById={assetsById}
              setInjectedFiles={setInjectedFiles}
              injectedAssets={setInjectedAssets}
              setInjectedAssets={setInjectedAssets}
              handlePinToggle={handlePinToggle}
              handleAssetPinToggle={handleAssetPinToggle}

              // Message Actions
              createThreadWithMessages={createThreadWithMessages}
              multiSelectEnabled={multiSelectEnabled}
              selectedMessageIds={selectedMessageIds}
              showProjectPanel={showProjectPanel}
              setShowProjectPanel={setShowProjectPanel}
              showTagPanel={showTagPanel}
              setShowTagPanel={setShowTagPanel}
              showThreadPanel={showThreadPanel}
              setShowThreadPanel={setShowThreadPanel}
              showSingleThreadPanel={showSingleThreadPanel}
              setShowSingleThreadPanel={setShowSingleThreadPanel}
              handleToggleMultiSelect={handleToggleMultiSelect}
              handleToggleSelect={handleToggleSelect}
              onMultiAction={onMultiAction}
              handleCreateThread={handleCreateThread}
              handleJoinThread={handleJoinThread}
              handleLeaveThread={handleLeaveThread}
              tagDialogOpen={tagDialogOpen}
              setTagDialogOpen={setTagDialogOpen}
              handleConfirmProject={handleConfirmProject}
              handleConfirmTagsAdd={handleConfirmTagsAdd}
              handleConfirmTagsRemove={handleConfirmTagsRemove}
              existingTagsForSelection={existingTagsForSelection}
              existingThreadsForSelection={existingThreadsForSelection}
              clearSelectionAndExit={clearSelectionAndExit}
              status={status}
              setStatus={setStatus}
            />
          </div>
          <div className="flex flex-col w-full md:max-w-sm sticky top-6 self-start h-[80vh] min-h-[400px]">
            {/* Expandable/collapsible presence panel */}
            <PresencePanel speaking={audioControls.speaking} />
            {/* MOTD Bar under the Presence Panel */}
            <MotdBar motd={motd} />
            {/* Always-scrollable tool panel below */}
            <div className="flex-1 overflow-y-auto">
            <TabbedToolPanel
              threads={threads}
              threadMap={threadMap}
              projects={projects}
              project={project}
              fetchProjects={fetchProjects}
              projectMap={projectMap}
              selectedProjectId={selectedProjectId}
              setSelectedProjectId={setSelectedProjectId}
              focus={focus}
              setFocus={setFocus}
              autoAssign={autoAssign}
              setAutoAssign={setAutoAssign}
              injectedFiles={injectedFiles}
              setInjectedFiles={setInjectedFiles}
              injectedAssets={injectedAssets}
              setInjectedAssets={setInjectedAssets}
              fetchFiles={fetchFiles}
              files={files}
              assetsByProjectId={assetsByProjectId}
              assetsById={assetsById}
              setFiles={setFiles}
              filesLoading={filesLoading}
              setFilesLoading={setFilesLoading}
              filesError={filesError}
              handlePinToggle={handlePinToggle}
              handleAssetPinToggle={handleAssetPinToggle}
            />
            </div>
          </div>
        </div>
      )}

      {activeTab === "history" && (
        <div className="flex-1 min-h-0 px-6 bg-neutral-950 text-white">
          <HistoryTab
            // Feature flags
            enableTTS={enableTTS}
            enablePublic={enablePublic}
            enableSync={enableSync}
            // General and nav
            audioControls={audioControls}

            // Project & Threads
            threads={threads}
            threadMap={threadMap}
            projects={projects}
            project={project}
            fetchProjects={fetchProjects}
            projectMap={projectMap}
            projectsLoading={projectsLoading}

            // Message Actions
            threadMessages={threadMessages}
            setThreadMessages={setThreadMessages}
            setChatMessages={setMessages}
            clearSelectionAndExit={clearSelectionAndExit}
            onReturnToThisMoment={handleReturnToThisMoment}
            createThreadWithMessages={createThreadWithMessages}
            multiSelectEnabled={multiSelectEnabled}
            selectedMessageIds={selectedMessageIds}
            showProjectPanel={showProjectPanel}
            setShowProjectPanel={setShowProjectPanel}
            showTagPanel={showTagPanel}
            setShowTagPanel={setShowTagPanel}
            showThreadPanel={showThreadPanel}
            setShowThreadPanel={setShowThreadPanel}
            showSingleThreadPanel={showSingleThreadPanel}
            setShowSingleThreadPanel={setShowSingleThreadPanel}
            handleToggleMultiSelect={handleToggleMultiSelect}
            handleToggleSelect={handleToggleSelect}
            handleCreateThread={handleCreateThread}
            handleJoinThread={handleJoinThread}
            handleLeaveThread={handleLeaveThread}
            tagDialogOpen={tagDialogOpen}
            setTagDialogOpen={setTagDialogOpen}
            handleConfirmProject={handleConfirmProject}
            existingTagsForSelection={existingTagsForSelection}
            existingThreadsForSelection={existingThreadsForSelection}
            clearSelectionAndExit={clearSelectionAndExit}
          />
        </div>
      )}
    </div>
  );
}