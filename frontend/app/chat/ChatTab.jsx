// app/chat/ChatTab.jsx
// ChatPage layout:
// 1) Controls
// 2) Chat and Formatting
// 3) Files and Attachments
// 4) Message Actions States and Functions
// 5) Rendering (tabs + layout)
"use client";
import React from "react";
import { useState, useEffect, useRef, useMemo } from "react";
// Hooks
import { useConfig } from '@/hooks/ConfigContext';
// Components
import MessageItem from "@/components/app/MessageItem";
import MultiActionBar from "@/components/app/MultiActionBar"
import ProjectPickerPanel from "@/components/app/ProjectPickerPanel"
import TagPanel from "@/components/app/TagPanel"
import ThreadPanel from "@/components/app/ThreadPanel";
import { Toggle } from "@/components/ui/toggle"
import { IconToggleButton } from "@/components/ui/icon-toggle-button"
// Utils
import { assignMessageId, toPythonIsoString, fileToBase64, trimMessages, generateAssetId, inferAssetTypeFromMime } from '@/utils/utils';

// Icons
import {
  ArrowBigDownDash,
  Paperclip,
  Pin,
  Pencil,
  Sparkles,
  History,
  Slash,
  Split,
  Headphones,
  Bell,
  BellOff,
  MessageCircleMore,
  MessageCircleX
  } from 'lucide-react';
function HistoryOffIcon(props) {
  return (
    <span className="relative inline-flex h-4 w-4" {...props}>
      <History className="absolute inset-0" />
      <Slash className="absolute inset-0" />
    </span>
  );
}

const ChatTab = (
  {
    // Feature flags
    enableTTS,
    // General and nav
    audioControls,
    ephemeralFiles,
    setEphemeralFiles,
    editingEphemeralId,
    setEditingEphemeralId,
    ephemeralNameDraft,
    setEphemeralNameDraft,
    handleEphemeralRename,
    handleEphemeralUpload,
    messages,
    setMessages,
    threadMessages,
    setThreadMessages,
    setAltMessages,
    wsRef,
    connecting,
    thinking,
    setThinking,
    scrollToMessageId,
    setScrollToMessageId,
    ACTIVE_WINDOW_LIMIT,
    timeSkipOverride,
    setTimeSkipOverride,
    timeSkipActive,

    // Project & Threads
    threadId = null,
    threadTitle = null,
    threads,
    threadMap,
    projects,
    project,
    projectMap,
    projectsLoading,
    selectedProjectId,
    focus,
    autoAssign,
    injectedFiles,
    files,
    assetsByProjectId,
    assetsById,
    setInjectedFiles,
    injectedAssets,
    setInjectedAssets,
    handlePinToggle,
    handleAssetPinToggle,

    // Message Actions
    createThreadWithMessages,
    multiSelectEnabled,
    selectedMessageIds,
    showProjectPanel,
    setShowProjectPanel,
    showTagPanel,
    setShowTagPanel,
    showThreadPanel,
    setShowThreadPanel,
    showSingleThreadPanel,
    setShowSingleThreadPanel,
    handleToggleMultiSelect,
    handleToggleSelect,
    onMultiAction,
    handleCreateThread,
    handleJoinThread,
    handleLeaveThread,
    tagDialogOpen,
    setTagDialogOpen,
    handleConfirmProject,
    handleConfirmTagsAdd,
    handleConfirmTagsRemove,
    existingTagsForSelection,
    existingThreadsForSelection,
    clearSelectionAndExit,
    status,
    setStatus,
  }
) => {
  // ------------------------------------
  // Controls
  // ------------------------------------
  console.log("ChatTab render status:", status);
  const {
    autoTTS,
    setAutoTTS,
    silent,
    setSilent,
    } = audioControls;

  const mode = "chat";

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSubmit = async () => {
    if (!input.trim()) return;

    // 0. Start from what we currently believe
    let latestTimeSkip = uiStates?.time_skip;

    const thinksSkipActive =
      timeSkipOverride !== null
        ? timeSkipOverride
        : Boolean(latestTimeSkip?.active);

    // Only bother the backend if we *think* a skip is active
    try {
      const res = await fetch("/api/states/time_skip");
      if (res.ok) {
        const data = await res.json(); // [false, null, null]
        const latestTimeSkip = Array.isArray(data) ? data[0] : null;

        // If backend says it's not active, clear the override
        if (latestTimeSkip === false || latestTimeSkip === null) {
          setTimeSkipOverride(false);

        }
      }
    } catch (err) {
      console.error("Error refreshing time_skip:", err);
    }

    const allFiles = [
      ...injectedFiles,
    ];

    const filenamesBlock = allFiles.length
      ? '\n' + allFiles.map(f => `[file: ${f.name}]`).join('\n')
      : '';
    const timestamp = toPythonIsoString();
    const role = "user";
    const source = "webui";
    const message = input + (filenamesBlock ? '\n' + filenamesBlock : '');
    // sets the project_id on the message immediately
    const project_id = (autoAssign && selectedProjectId) ? selectedProjectId : "";
    const thread_id = threadId
    const ephemeralPayload = await Promise.all(
      ephemeralFiles.map(async (f, index) => {
        const asset_id = await generateAssetId(); // or sync crypto helper

        let data;
        try {
          data = await fileToBase64(f.file);
        } catch (err) {
          console.error("Failed reading ephemeral file", index, f, err);
          throw err;
        }

        return {
          asset_id,
          name: f.name,
          type: f.type,
          size: f.size,
          data: data,
          encoding: "base64",
          role: "attachment",
          display: "inline",
          order: index
        };
      })
    );

    const optimisticEphemeralAssets = ephemeralPayload.map((f, index) => ({
      asset_id: f.asset_id,
      asset_type: inferAssetTypeFromMime(f.type),
      mimetype: f.type,
      filename: f.name,
      display_name: f.name,
      size: f.size,

      role: "attachment",
      display: f.type?.startsWith("image/") ? "inline" : "download",
      order: index,

      source_type: "chat_upload",
      bytes_status: "pending",
      preview_url: f.preview_url,
    }));

    const optimisticInjectedAssets = injectedAssets
      .map(({ id: assetId }, index) => {
        const asset = assetsById[assetId];
        if (!asset) return null;

        const mimetype = asset.mimetype || asset.mime_type || asset.type;
        const filename =
          asset.display_name ||
          asset.filename ||
          asset.name ||
          asset.original_filename ||
          assetId;

        return {
          asset_id: asset.asset_id || asset.id || assetId,
          asset_type: asset.asset_type || inferAssetTypeFromMime(mimetype),
          mimetype,
          filename,
          display_name: asset.display_name || filename,
          size: asset.size ?? asset.size_bytes,

          role: "attachment",
          display: mimetype?.startsWith("image/") ? "inline" : "download",

          // Continue after newly uploaded ephemeral items.
          order: ephemeralPayload.length + index,

          // Preserve the asset's actual provenance.
          source_type: asset.source_type,
          bytes_status:
            asset.bytes_status ||
            asset.storage?.bytes_status ||
            "available",

          // Only include this if your asset listing endpoint already returns
          // a usable content/preview URL.
          preview_url: asset.preview_url || asset.content_url,
        };
      })
      .filter(Boolean);

    const optimisticAssets = [
      ...optimisticEphemeralAssets,
      ...optimisticInjectedAssets,
    ];

    // 1. Generate the message_id (async)//
    const message_id = await assignMessageId({
      timestamp,
      role,
      source,
      message
    });

    // 2. Add to UI state immediately (so it’s taggable, traceable, etc.)//
    setMessages(prev =>
      trimMessages([
        ...prev,
        {
          id: message_id,
          message_id,
          text: message,
          timestamp,
          role,
          source,
          project_id,
          thread_ids: [threadId],
          metadata: {
            assets: optimisticAssets
          }
        }
      ], ACTIVE_WINDOW_LIMIT)
    );
      if (threadId) {
        setThreadMessages(prev =>
          trimMessages([
            ...prev,
            {
              id: message_id,
              message_id,
              text: message,
              timestamp,
              role,
              source,
              project_id,
              thread_ids: [threadId],
              metadata: {
                assets: optimisticAssets
              }
            }
          ], ACTIVE_WINDOW_LIMIT)
        );
      }

    setStatus(["Sending message..."]);
    setInput("");
    setThinking(true);
    //setScrollToBottom(true);

    // 3. Send the message to the backend, including timestamp
    await fetch("/api/muse/talk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: message,
        timestamp,
        message_id,
        project_id: selectedProjectId,
        thread_id: threadId,
        auto_assign: autoAssign,
        blend_ratio: focus,
        injected_files: injectedFiles.map(f => f.id),
        injected_assets: injectedAssets.map(a => a.id),
        ephemeral_files: ephemeralPayload,
        source: "webui",
        prompt_type: "webui"
      }),
    });

    // 4. Clean up ephemerals (only keep pinned) //
    clearEphemeralFiles();
  };

  // ------------------------------------
  // End - Controls
  // ------------------------------------


  // ------------------------------------
  // Chat and Formatting
  // ------------------------------------
  const [input, setInput] = useState("");
  const [hasMore, setHasMore] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [scrollToBottom, setScrollToBottom] = useState(true);
  const [scrollTargetNode, setScrollTargetNode] = useState(null);
  const [atBottom, setAtBottom] = useState(true);
  const chatEndRef = useRef(null);
  const scrollContainerRef = useRef(null);
  const messageRefs = useRef({});
  const { museProfile, museProfileLoading, uiStates, userConfig, updateUserConfig } = useConfig();
  const museName = museProfile?.name?.[0]?.content ?? "Muse";
  const INITIAL_RENDERED_MESSAGES = 10;  // On reload, after chat, etc.
  const SCROLLBACK_LIMIT = 30;            // After scroll up
  const MAX_RENDERED_MESSAGES = 30;      // Max after scroll loading "more"
  const MESSAGE_LIMIT = 10;              // How many to load per scroll/page
  const whichMessages = React.useMemo(() => {
    if (threadId) {
      // In a thread: show every message that belongs to this thread,
      // regardless of hidden/private.
      return threadMessages.filter((m) => m.thread_ids?.includes(threadId));
    }

    // In main chat: hide messages whose thread_ids intersect hidden/private threads
    return messages.filter((m) => {
      const tids = m.thread_ids || [];
      if (!tids.length) return true; // plain main-river message

      // If ANY of the message's threads are hidden/private, drop it from main view
      const belongsToHidden = tids.some((id) => {
        const t = threadMap.threads[id];
        return t && (t.is_hidden || t.is_private);

        });

      return !belongsToHidden;
    });

  }, [threadId, threadMessages, messages, threads]);

  const safeMessages = Array.isArray(whichMessages) ? whichMessages : [];

  const visibleMessages = React.useMemo(
    () => safeMessages.slice(-MAX_RENDERED_MESSAGES),
    [safeMessages, MAX_RENDERED_MESSAGES]
  );

  const [useLabRenderer, setUseLabRenderer] = React.useState(false);
  useEffect(() => {
    if (scrollTargetNode) {
      scrollTargetNode.scrollIntoView({ behavior: "smooth", block: "start" });
      setScrollTargetNode(null);
      setScrollToMessageId(null);
    }
  }, [scrollTargetNode]);

  const formatTimestamp = (utcString) => {
    if (!utcString) return "";
    const dt = new Date(utcString);
    return dt.toLocaleString(); // Respects user timezone/locales
  };

  function buildMessagesUrl({ before, sources, threadId } = {}) {
    const params = new URLSearchParams();

    params.set("limit", INITIAL_RENDERED_MESSAGES.toString());

    // sources: array of strings → multiple ?sources=... entries
    const srcs = sources && sources.length
      ? sources
      : ["frontend", "webui", "reminder", "discovery", "initiative"];

    srcs.forEach(src => params.append("sources", src));

    if (before) {
      params.set("before", before); // URLSearchParams handles encoding
    }

    if (threadId) {
      params.set("thread_id", threadId);
    }

    return `/api/messages?${params.toString()}`;
  }

  const handleLoadMore = async () => {
    if (!hasMore || loadingMore) return;

    const isThread = !!threadId;
    const currentList = isThread ? threadMessages : messages;

    if (!currentList.length) return;

    const oldest = currentList[0]?.timestamp;
    if (!oldest) return;

    await loadMessages({
      before: oldest,
      target: isThread ? "thread" : "main",
    });
  };

  const loadMessages = async ({
    before = null,
    target = "main", // "main" | "thread"
  } = {}) => {
    setLoadingMore(true);

    let prevScrollHeight = null;
    let prevScrollTop = null;

    const isHistoryLoad = !!before;

    // Only care about previous scroll position if loading history
    if (isHistoryLoad && scrollContainerRef.current) {
      prevScrollHeight = scrollContainerRef.current.scrollHeight;
      prevScrollTop = scrollContainerRef.current.scrollTop;
    }

    const url = buildMessagesUrl({
      before,
      threadId: target === "thread" ? threadId : null, // use current threadId when targeting thread
    });

    const res = await fetch(url);
    const data = await res.json();

    if (isHistoryLoad) {
      if (target === "thread") {
        setThreadMessages(prev =>
          trimMessages([...data.messages, ...prev], SCROLLBACK_LIMIT)
        );
      } else {
        setMessages(prev =>
          trimMessages([...data.messages, ...prev], SCROLLBACK_LIMIT)
        );
      }

      setScrollToBottom(false); // Don't scroll when loading history

      // After next render, restore the scroll position so the previous top message stays in place
      setTimeout(() => {
        requestAnimationFrame(() => {
          if (
            scrollContainerRef.current &&
            prevScrollHeight !== null &&
            prevScrollTop !== null
          ) {
            const newScrollHeight = scrollContainerRef.current.scrollHeight;
            scrollContainerRef.current.scrollTop =
              newScrollHeight - prevScrollHeight + prevScrollTop;
          }
        });
      }, 0);
    } else {
      if (target === "thread") {
        setThreadMessages(trimMessages(data.messages, ACTIVE_WINDOW_LIMIT));
      } else {
        setMessages(trimMessages(data.messages, ACTIVE_WINDOW_LIMIT));
      }

      // If you want auto-scroll on fresh loads, you can re‑enable this:
       setScrollToBottom(true);
    }

    if (data.messages.length === SCROLLBACK_LIMIT) {
      setHasMore(false);
    }

    setLoadingMore(false);
  };

  useEffect(() => {
    loadMessages({ target: "main" });
    // eslint-disable-next-line
  }, []);

  useEffect(() => {
    if (!threadId) {
      // Optional: clear threadMessages when leaving thread mode
      setThreadMessages([]);
      return;
    }

    // when a thread becomes active, load its messages
    loadMessages({ target: "thread" });
    // eslint-disable-next-line
  }, [threadId]);

  const lastVisibleId = visibleMessages.length
    ? visibleMessages[visibleMessages.length - 1].message_id
    : null;

  const statusCount = Array.isArray(status) ? status.length : 0;

  useEffect(() => {
    if (scrollToBottom) {
      chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [lastVisibleId, statusCount, scrollToBottom]);


  useEffect(() => {
    if (
      scrollToMessageId &&
      scrollContainerRef.current &&
      messageRefs.current[scrollToMessageId]?.current
    ) {
      const container = scrollContainerRef.current;
      const messageEl = messageRefs.current[scrollToMessageId].current;

      const offsetTop = messageEl.offsetTop - container.offsetTop;
      container.scrollTo({
        top: offsetTop,
        behavior: "smooth",
      });

      setScrollToMessageId(null);
    }
  }, [scrollToMessageId, visibleMessages]);
  // ------------------------------------
  // End - Chat and Formatting
  // ------------------------------------

  // ------------------------------------
  // Files and Attachments
  // ------------------------------------
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef(null);
  const ACCEPTED_TYPES = [
    ".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".js", ".ts", ".py", ".java", ".c", ".cpp", ".cs", ".go", ".rb", ".php",
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"
  ];
  const handleFileInputChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    handleEphemeralUpload(file); // Use your upload logic here!
    e.target.value = "";
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) handleEphemeralUpload(file);
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
  };

  const handlePaste = (e) => {
    if (!e.clipboardData || !e.clipboardData.items) return;

    // Look for image files in the clipboard
    for (let i = 0; i < e.clipboardData.items.length; i++) {
      const item = e.clipboardData.items[i];
      if (item.type.startsWith('image/')) {
        const file = item.getAsFile();
        if (file) {
          handleEphemeralUpload(file);
          // Optionally: prevent image from being pasted as base64 text into textarea
          e.preventDefault();
        }
      }
    }
  };

  const mergedFiles = [
    ...ephemeralFiles.map(f => ({
      id: f.id,
      name: f.name,
      type: f.type,
      size: f.size,
      file: f.file,
      source: "ephemeral",
    })),

    ...injectedFiles.map(({ id: fileId, pinned }) => {
      const file = files.find(f => f.id === fileId);
      if (!file) return null;

      return {
        id: fileId,
        name: file.name,
        type: file.type,
        size: file.size,
        pinned,
        source: "injected",
        file,
      };
    }),

    ...injectedAssets.map(({ id: assetId, pinned }) => {
      const asset = assetsById[assetId];
      if (!asset) return null;

      return {
        id: assetId,
        name:
          asset.display_name ||
          asset.filename ||
          asset.name ||
          asset.original_filename ||
          assetId,
        type: asset.mime_type || asset.type,
        size: asset.size_bytes || asset.size,
        pinned,
        source: "asset",
        asset,
      };
    }),
  ].filter(Boolean);

  const clearEphemeralFiles = () => {
    setInjectedFiles(prev => prev.filter(f => f.pinned));
    setInjectedAssets(prev => prev.filter(a => a.pinned));
    setEphemeralFiles([]);
  };

  // ------------------------------------
  // End - Files and Attachments
  // ------------------------------------

  // ------------------------------------
  // Message Actions States and Functions
  // ------------------------------------
  const [newTag, setNewTag] = useState("");
  const [projectDialogOpen, setProjectDialogOpen] = useState(null); // message id or null
  const [threadPanelOpen, setThreadPanelOpen] = useState(null);
  const [newProject, setNewProject] = useState("");



  async function handleClearTimeSkip() {
    try {
      // optimistic UI: flip it *now*
      setTimeSkipOverride(false);

      await fetch("/api/time_skip/clear", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      loadMessages()
      // optional: once the next poll confirms, you can clear override
      // setTimeSkipOverride(null);
    } catch (err) {
      console.error("Error clearing time skip:", err);
      // if you want to be fancy, roll back:
      setTimeSkipOverride(null);
    }
  }

  useEffect(() => {
    if (timeSkipOverride === null) return;

    const backendActive = Boolean(uiStates?.time_skip?.active);

    // if backend has caught up with our optimistic value, drop override
    if (backendActive === timeSkipOverride) {
      setTimeSkipOverride(null);
    }
  }, [uiStates?.time_skip?.active, timeSkipOverride]);

  // ------------------------------------
  // End - Message Actions States and Functions
  // ------------------------------------
  const onToggleAutoTTS = () => {
    setAutoTTS((prev) => !prev);
  };
  const onToggleSilent = () => {
    setSilent((prev) => !prev);
  };

  const unpromptedMessages = userConfig?.muse_features?.ENABLE_UNPROMPTED_MESSAGING ?? true;
  const handleSaveUnpromptedMessages = async () => {
    if (!userConfig) return;

    const currentMuseFeatures = userConfig.muse_features || {};

    const nextMuseFeatures = {
      ...currentMuseFeatures,
      ENABLE_UNPROMPTED_MESSAGING: !unpromptedMessages,
    };

    try {
      await updateUserConfig({
        section: "muse_features",
        data: nextMuseFeatures,
      });
    } catch (err) {
      console.error("Failed to update unprompted messaging setting:", err);
    }
  };

  return (
    <div className="relative flex flex-col h-full ">
      <div className="flex items-center justify-between mt-4">
        {/* Left side: Auto-TTS controls */}
        <div className="flex gap-2 items-center">
        {enableTTS && (
          <>
            <IconToggleButton
              pressed={autoTTS}
              onClick={() => setAutoTTS(v => !v)}
              title="Auto‑read new messages"
              disabled={thinking || connecting}
            >
              <Headphones className="h-4 w-4" />
            </IconToggleButton>
          </>
        )}
          <IconToggleButton
            pressed={silent}
            onClick={() => setSilent(v => !v)}
            title="Disable message pings"
            disabled={thinking || connecting}
          >
            {silent ? <BellOff className="h-4 w-4" /> : <Bell className="h-4 w-4" />}
          </IconToggleButton>
          <IconToggleButton
            pressed={!unpromptedMessages}
            onClick={handleSaveUnpromptedMessages}
            title="Disable unprompted messages"
            disabled={thinking || connecting}
          >
            {unpromptedMessages ? <MessageCircleMore className="h-4 w-4" /> : <MessageCircleX className="h-4 w-4" />}
          </IconToggleButton>
        </div>

        {/* // Uncomment this to experiment with different renderers
        <div className="flex items-center justify-end px-2 py-1 text-xs text-neutral-400 gap-2">
          <span>Renderer:</span>
          <button
            type="button"
            className={`px-2 py-0.5 rounded ${
              !useLabRenderer ? "bg-purple-700 text-white" : "bg-neutral-800"
            }`}
            onClick={() => setUseLabRenderer(false)}
          >
            Legacy
          </button>
          <button
            type="button"
            className={`px-2 py-0.5 rounded ${
              useLabRenderer ? "bg-purple-700 text-white" : "bg-neutral-800"
            }`}
            onClick={() => setUseLabRenderer(true)}
          >
            Markdown Lab
          </button>
        </div>
        */}

        {threadId && (
          <div className="absolute left-1/3 top-20 mt-0 z-20 flex justify-end">
            <span className="bg-purple-900 text-sm text-purple-300 px-4 py-0.5 rounded-lg flex items-center gap-1">
              <Split size={14} className="inline" />
              <span className="font-semibold">
                You are currently in thread: {threadMap.threads[threadId].title || "Thread"}
              </span>
            </span>
          </div>
        )}
        {/* Right side: Message actions */}
        <div className="ml-auto">
          <MultiActionBar
            multiSelectEnabled={multiSelectEnabled}
            onToggleMultiSelect={handleToggleMultiSelect}
            selectedCount={selectedMessageIds.length}
            onAction={onMultiAction}
            disabled={thinking || connecting}
            setShowProjectPanel={setShowProjectPanel}
            setShowTagPanel={setShowTagPanel}
            setShowThreadPanel={setShowThreadPanel}
          />
        </div>
        {/* Overlay row for complex actions */}
        {showProjectPanel && (
          <div className="absolute right-0 top-12 mt-0 z-20 flex justify-end">
            {console.log(">>> ProjectPickerPanel block is rendering")}
            <ProjectPickerPanel
              projects={projects}
              onConfirm={handleConfirmProject}
              onCancel={() => setShowProjectPanel(false)}
            />
          </div>
        )}

        {showTagPanel && (
          <div className="absolute right-0 top-12 mt-0 z-20 flex justify-end">
            <TagPanel
              mode={showTagPanel}
              existingTags={existingTagsForSelection}
              onConfirm={
                showTagPanel === "add"
                  ? handleConfirmTagsAdd
                  : handleConfirmTagsRemove
              }
              onCancel={() => setShowTagPanel(null)}
            />
          </div>
        )}
        {showThreadPanel && (
          <div className="absolute right-0 top-12 mt-0 z-20 flex justify-end">
            <ThreadPanel
              mode={showThreadPanel}
              msg_ids={selectedMessageIds}
              threads={threads}
              memberThreadIds={existingThreadsForSelection}
              onCreateThread={handleCreateThread}
              onJoinThread={handleJoinThread}
              onLeaveThread={handleLeaveThread}
              clearSelectionAndExit={clearSelectionAndExit}
              onCancel={() => setShowThreadPanel(false)}
            />
          </div>
        )}

      </div>
        {!atBottom && (
        <button
          type="button"
          onClick={() => {
            chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
          }}
          className="
            absolute
            bottom-28
            left-1/2
            -translate-x-1/2
            z-20
            bg-purple-700 text-white px-3 py-1 rounded-full shadow-lg
            hover:bg-purple-800 transition
          "
        >
          <ArrowBigDownDash />
        </button>
      )}
        <div
          ref={scrollContainerRef}
          className="mt-4 flex-1 min-h-0 overflow-y-auto relative pt-12"
          onScroll={async (e) => {
            const { scrollTop, scrollHeight, clientHeight } = e.target;

            if (scrollTop + clientHeight >= scrollHeight - 10) {
              setAtBottom(true);
            } else {
              setAtBottom(false);
            }

            if (scrollTop === 0) {
              await handleLoadMore();
            }
          }}
        >

        <div className="text-sm text-neutral-400 italic text-center mt-2">
          That’s the beginning. Visit the History Tab for more.
        </div>
        {connecting && (
          <div className="text-sm text-neutral-400">Reconnecting…</div>
        )}

          {visibleMessages.map((msg, idx) => {
            if (!messageRefs.current[msg.message_id]) {
              messageRefs.current[msg.message_id] = React.createRef();
            }
            const key = msg.message_id || idx;
            const CommonProps = {
              ref: messageRefs.current[msg.message_id],
              audioControls,
              msg,
              setMessages,
              setThreadMessages,
              setAltMessages,
              projects,
              projectsLoading,
              projectMap,
              threads,
              tagDialogOpen,
              setTagDialogOpen,
              projectDialogOpen,
              setProjectDialogOpen,
              museName,
              mode,
              connecting,
              createThreadWithMessages,
              setShowSingleThreadPanel,
              setThreadPanelOpen,
              showSingleThreadPanel,
              multiSelectEnabled,
              handleCreateThread,
              handleJoinThread,
              handleLeaveThread,
              clearSelectionAndExit,
              isSelected: selectedMessageIds.includes(msg.message_id),
              onToggleSelect: handleToggleSelect,
            };
            return <MessageItem key={key} {...CommonProps} />;
          })}
        {thinking && (
          <div className="text-sm text-neutral-500 italic whitespace-pre-wrap">
            {status.join("\n")}
          </div>
        )}
        <div ref={chatEndRef} />
      </div>
      <div className="mt-2 shrink-0">
      {mergedFiles.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {mergedFiles.map(f => {
            // Icon logic
            let Icon;
            let iconTitle;
            let tileBg = "";
            let badge = null;

            if (f.source === "ephemeral") {
              Icon = /* your ephemeral icon, e.g. */ Sparkles || PaperAirplaneIcon;
              iconTitle = "Ephemeral file (not saved)";
              tileBg = "bg-blue-950/80 border border-blue-300";

            } else if (f.pinned) {
              Icon = Pin;
              iconTitle = "Pinned file";
              tileBg = "bg-purple-900 border-2 border-purple-500";
            } else {
              Icon = Paperclip;
              iconTitle = "Injected file";
              tileBg = "bg-white/10 border border-white/15";
            }

            return (
              <span
                key={f.id}
                className={`
                  flex items-center px-2 py-1 rounded-md shadow-sm text-xs font-medium
                  transition hover:bg-white/20 cursor-default select-none
                  ${tileBg}
                  text-purple-100 max-w-[200px] backdrop-blur-[2px]
                `}
              >
                {/* Icon */}
                <Icon
                  className={`w-4 h-4 shrink-0 mr-1 ${
                    f.pinned
                      ? "text-yellow-300 opacity-100"
                      : f.source === "ephemeral"
                      ? "text-blue-300 opacity-90"
                      : "text-purple-300 opacity-70"
                  }`}
                  strokeWidth={2}
                  title={iconTitle}
                />

                {/* File name */}
                {f.source === "ephemeral" && editingEphemeralId === f.id ? (
                  <input
                    autoFocus
                    value={ephemeralNameDraft}
                    onChange={(e) => setEphemeralNameDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        handleEphemeralRename(f.id, ephemeralNameDraft);
                        setEditingEphemeralId(null);
                      }

                      if (e.key === "Escape") {
                        setEditingEphemeralId(null);
                      }
                    }}
                    onBlur={() => {
                      handleEphemeralRename(f.id, ephemeralNameDraft);
                      setEditingEphemeralId(null);
                    }}
                    aria-label="Ephemeral file name"
                    className="
                      min-w-0 max-w-[120px]
                      bg-black/30 border border-blue-300/60 rounded
                      px-1 py-0.5 text-xs text-purple-100
                      outline-none focus:border-blue-200
                    "
                  />
                ) : (
                  <span
                    className="truncate max-w-[120px]"
                    title={f.name}
                  >
                    {f.name.length > 32 ? f.name.slice(0, 29) + "..." : f.name}
                  </span>
                )}
                {badge}
                {f.source === "ephemeral" && editingEphemeralId !== f.id && (
                  <button
                    onClick={() => {
                      setEditingEphemeralId(f.id);
                      setEphemeralNameDraft(f.name);
                    }}
                    aria-label={`Rename ${f.name}`}
                    title="Rename ephemeral file"
                    className="
                      ml-1 text-blue-300/75 hover:text-blue-100
                      focus:outline-none transition
                    "
                    type="button"
                  >
                    <Pencil className="w-3.5 h-3.5" strokeWidth={2} />
                  </button>
                )}

                {/* Remove button */}
                <button
                  onClick={() => {
                    if (f.source === "ephemeral") {
                      setEphemeralFiles(files => files.filter(x => x.id !== f.id));
                    } else if (f.source === "injected") {
                      setInjectedFiles(prev => prev.filter(x => x.id !== f.id));
                    } else {
                      setInjectedAssets(prev => prev.filter(x => x.id !== f.id));
                    }
                  }}
                  aria-label={`Remove ${f.name}`}
                  className="
                    ml-2
                    text-purple-300 hover:text-red-400
                    text-base font-bold
                    focus:outline-none
                    transition
                    px-0.5 leading-none
                  "
                  type="button"
                  tabIndex={0}
                >
                  ×
                </button>
                {/* Pin toggle only for injected */}
                {f.source === "injected" && (
                  <button
                    onClick={() => handlePinToggle(f.id)}
                    aria-label={f.pinned ? `Unpin ${f.name}` : `Pin ${f.name}`}
                    className="ml-1 focus:outline-none"
                    type="button"
                    tabIndex={0}
                    title={f.pinned ? "Unpin file" : "Pin file"}
                    style={{ background: "none", border: 0, padding: 0, display: "flex", alignItems: "center" }}
                  >
                    <Pin
                      className={`w-4 h-4 shrink-0 ${
                        f.pinned
                          ? "text-yellow-300 opacity-100"
                          : "text-purple-300 opacity-60"
                      }`}
                      strokeWidth={2}
                    />
                  </button>
                )}
                {f.source === "asset" && (
                  <button
                    onClick={() => handleAssetPinToggle(f.id)}
                    aria-label={f.pinned ? `Unpin ${f.name}` : `Pin ${f.name}`}
                    className="ml-1 focus:outline-none"
                    type="button"
                    tabIndex={0}
                    title={f.pinned ? "Unpin file" : "Pin file"}
                    style={{ background: "none", border: 0, padding: 0, display: "flex", alignItems: "center" }}
                  >
                    <Pin
                      className={`w-4 h-4 shrink-0 ${
                        f.pinned
                          ? "text-yellow-300 opacity-100"
                          : "text-purple-300 opacity-60"
                      }`}
                      strokeWidth={2}
                    />
                  </button>
                )}
              </span>
            );
          })}
        </div>
      )}
      <div className="flex gap-1 items-stretch w-full">
        {/* Textarea wrapper is the flex child now */}
        <div className="relative flex-1 min-w-0">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={3}
            className="w-full p-2 pr-9 rounded-lg bg-neutral-800 text-white resize-none border border-neutral-700 focus:border-purple-500 focus:outline-none"
            placeholder={`Say something to ${museName}...`}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onPaste={handlePaste}
            style={{
              background: dragActive ? "#a78bfa22" : undefined,
              border: dragActive ? "2px dashed #a78bfa" : undefined,
              borderRadius: dragActive ? 10 : undefined,
              transition: "border 0.15s, background 0.15s"
            }}
          />

          {/* Time-skip badge in the textarea corner */}
          {timeSkipActive && (
            <button
              className="absolute top-2 right-2 flex h-7 w-7 items-center justify-center
                         rounded-md text-neutral-300 hover:text-purple-200
                         bg-transparent hover:bg-neutral-800/40"
              title="Return to present (clear time filter)"
              onClick={handleClearTimeSkip}
            >
              <HistoryOffIcon className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Attach button: tall, narrow */}
        <button
          type="button"
          className="
            flex items-center justify-center
            bg-neutral-900 border border-purple-600
            rounded-lg
            px-0
            py-2
            h-full
            w-[42px]
            hover:bg-purple-950/30 transition
            text-purple-300
            focus:outline-none
            select-none
            shadow-sm
          "
          style={{
            minHeight: "90px", // Or match the Send button's actual height
          }}
          onClick={() => fileInputRef.current && fileInputRef.current.click()}
          aria-label="Attach file"
          tabIndex={0}
        >
          <Paperclip className="w-5 h-5" strokeWidth={2.2} />
        </button>

        {/* Send button: unchanged, big & square */}
        <button
          onClick={handleSubmit}
          className="
            bg-purple-700
            text-white
            px-6
            py-4
            rounded-lg
            hover:bg-purple-800
            h-full
          "
          style={{
            minHeight: "90px", // Or match the Send button's actual height
          }}
        >
          Send
        </button>

        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_TYPES.join(",")}
          style={{ display: "none" }}
          onChange={handleFileInputChange}
          multiple={false}
        />
      </div>
      </div>
    </div>
  );
};

export default ChatTab;
