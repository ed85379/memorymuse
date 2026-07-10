"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  LoaderCircle,
  ImageIcon,
  FileText,
  FileArchive,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Download,
  Eye,
  Clock,
  FolderKanban,
  Trash2,
  Pencil,
  Upload,
  X,
} from "lucide-react";
import { useConfig } from '@/hooks/ConfigContext';
import { updateFilesState } from "@/utils/statesFunctions";

function humanFileSize(bytes) {
  if (bytes === null || bytes === undefined || Number.isNaN(Number(bytes))) {
    return "—";
  }

  bytes = Number(bytes);

  const thresh = 1024;
  if (Math.abs(bytes) < thresh) return bytes + " B";

  const units = ["KB", "MB", "GB", "TB"];
  let u = -1;

  do {
    bytes /= thresh;
    ++u;
  } while (Math.abs(bytes) >= thresh && u < units.length - 1);

  return bytes.toFixed(1) + " " + units[u];
}

function formatDate(value) {
  if (!value) return "—";

  try {
    return new Date(value).toLocaleString();
  } catch {
    return "—";
  }
}

function normalizeAssetId(asset) {
  return asset?._id || asset?.asset_id || asset?.id;
}

function normalizeProjectIds(asset) {
  const projectIds = asset?.project_ids || asset?.projects || [];

  if (!Array.isArray(projectIds)) return [];

  return projectIds.map((p) => {
    if (typeof p === "string") return p;
    return p?._id || p?.id || p?.project_id || String(p);
  });
}

function getProjectId(project) {
  return project?._id || project?.id || project?.project_id;
}

function getProjectName(project) {
  return project?.name || project?.title || getProjectId(project) || "Untitled Project";
}

function getAssetDisplayName(asset) {
  return (
    asset?.display_name ||
    asset?.filename ||
    asset?.name ||
    normalizeAssetId(asset) ||
    "Untitled Asset"
  );
}

function getAssetType(asset) {
  const mimetype = asset?.mimetype || "";
  const assetType = asset?.asset_type || "";

  if (assetType) return assetType;
  if (mimetype.startsWith("image/")) return "image";
  if (mimetype.startsWith("text/")) return "text";
  if (mimetype === "application/pdf") return "pdf";
  if (mimetype.startsWith("audio/")) return "audio";
  if (mimetype.startsWith("video/")) return "video";

  return "file";
}

function isImageAsset(asset) {
  const mimetype = asset?.mimetype || "";
  const assetType = getAssetType(asset);
  return mimetype.startsWith("image/") || assetType === "image";
}

function getLifecycleStatus(asset) {
  const lifecycle = asset?.lifecycle || {};
  return lifecycle.status || asset?.lifecycle_status || asset?.status || "available";
}

function getAssetSize(asset) {
  return (
    asset?.size ||
    asset?.bytes ||
    asset?.storage?.size ||
    asset?.storage?.bytes ||
    asset?.metadata?.size ||
    0
  );
}

function getCreatedAt(asset) {
  return (
    asset?.created_at ||
    asset?.created_on ||
    asset?.uploaded_at ||
    asset?.uploaded_on ||
    asset?.lifecycle?.created_at ||
    asset?.provenance?.ingested_at ||
    asset?.metadata?.created_at
  );
}

function getSourceType(asset) {
  return asset?.source_type || asset?.source || "unknown";
}

function getAssetContentUrl(asset, variant = "original", download = false) {
  const assetId = normalizeAssetId(asset);
  if (!assetId) return "#";

  const params = new URLSearchParams();

  if (variant) params.set("variant", variant);
  if (download) params.set("download", "true");

  const query = params.toString();
  return `/api/assets/${assetId}/content${query ? `?${query}` : ""}`;
}

function isIndexableTextFile(file) {
  if (!file?.name) return false;
  return /\.(txt|md)$/i.test(file.name);
}

function sortAssets(assets, orderBy) {
  const copy = [...assets];

  copy.sort((a, b) => {
    const aName = getAssetDisplayName(a).toLowerCase();
    const bName = getAssetDisplayName(b).toLowerCase();

    const aDateValue = getCreatedAt(a);
    const bDateValue = getCreatedAt(b);

    const parseTime = (value) => {
      if (!value) return 0;

      const time = new Date(value).getTime();
      return Number.isNaN(time) ? 0 : time;
    };

    const aTime = parseTime(getCreatedAt(a));
    const bTime = parseTime(getCreatedAt(b));

    const aSize = Number(getAssetSize(a) || 0);
    const bSize = Number(getAssetSize(b) || 0);

    if (orderBy === "oldest") return aTime - bTime;
    if (orderBy === "name_asc") return aName.localeCompare(bName);
    if (orderBy === "name_desc") return bName.localeCompare(aName);
    if (orderBy === "size_desc") return bSize - aSize;
    if (orderBy === "size_asc") return aSize - bSize;

    // Default: newest first.
    return bTime - aTime;
  });

  return copy;
}

function AssetTypeIcon({ asset }) {
  const assetType = getAssetType(asset);

  if (assetType === "image") {
    return <ImageIcon size={32} className="text-violet-300" />;
  }

  if (assetType === "text" || assetType === "pdf") {
    return <FileText size={32} className="text-sky-300" />;
  }

  return <FileArchive size={32} className="text-zinc-300" />;
}

function StatusChip({ children, tone = "neutral", title }) {
  const toneClass =
    tone === "green"
      ? "border-emerald-500/40 bg-emerald-950/40 text-emerald-200"
      : tone === "violet"
        ? "border-violet-500/40 bg-violet-950/40 text-violet-200"
        : tone === "amber"
          ? "border-amber-500/40 bg-amber-950/40 text-amber-200"
          : tone === "red"
            ? "border-red-500/40 bg-red-950/40 text-red-200"
            : "border-zinc-600 bg-zinc-900/70 text-zinc-300";

  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${toneClass}`}
    >
      {children}
    </span>
  );
}

function sourceTone(sourceType) {
  if (sourceType === "generated") return "violet";
  if (sourceType === "user_upload") return "green";
  if (sourceType === "chat_upload") return "amber";
  return "neutral";
}

function lifecycleTone(status) {
  if (status === "available") return "green";
  if (status === "expired") return "amber";
  if (status === "deleted" || status === "purged" || status === "missing") return "red";
  return "neutral";
}

function EmptyState({ loading, error }) {
  if (loading) {
    return (
      <div className="flex min-h-[260px] items-center justify-center rounded-xl border border-zinc-800 bg-zinc-950/40 text-zinc-300">
        <div className="flex items-center gap-3">
          <LoaderCircle size={22} className="animate-spin text-violet-300" />
          <span>Loading assets…</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-[260px] items-center justify-center rounded-xl border border-red-900/70 bg-red-950/20 text-red-200">
        {error}
      </div>
    );
  }

  return (
    <div className="flex min-h-[260px] items-center justify-center rounded-xl border border-zinc-800 bg-zinc-950/40 text-zinc-400">
      No assets found.
    </div>
  );
}

function UploadAssetDialog({
  open,
  onClose,
  projects,
  projectsLoading,
  onUploaded,
}) {
  const fileInputRef = useRef(null);

  const [selectedFile, setSelectedFile] = useState(null);
  const [selectedProjectIds, setSelectedProjectIds] = useState([]);
  const [indexForRecall, setIndexForRecall] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);

  const canIndexForRecall = isIndexableTextFile(selectedFile);

  useEffect(() => {
    if (!open) return;

    setSelectedFile(null);
    setSelectedProjectIds([]);
    setIndexForRecall(false);
    setDragActive(false);
    setUploading(false);
    setUploadError(null);
  }, [open]);

  useEffect(() => {
    if (!canIndexForRecall) {
      setIndexForRecall(false);
    }
  }, [canIndexForRecall]);

  if (!open) return null;

  const activeProjects = (projects || []).filter((project) => !project.archived);

  const handleSelectFile = (file) => {
    if (!file) return;

    setSelectedFile(file);
    setUploadError(null);

    if (!isIndexableTextFile(file)) {
      setIndexForRecall(false);
    }
  };

  const handleFileInputChange = (event) => {
    const file = event.target.files?.[0] || null;
    handleSelectFile(file);
  };

  const handleDrop = (event) => {
    event.preventDefault();
    event.stopPropagation();

    setDragActive(false);

    const file = event.dataTransfer.files?.[0] || null;
    handleSelectFile(file);
  };

  const handleDragOver = (event) => {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(true);
  };

  const handleDragLeave = (event) => {
    event.preventDefault();
    event.stopPropagation();
    setDragActive(false);
  };

  const handleProjectSelection = (event) => {
    const ids = Array.from(event.target.selectedOptions).map((option) => option.value);
    setSelectedProjectIds(ids);
  };

  const handleUpload = async () => {
    if (!selectedFile || uploading) return;

    setUploading(true);
    setUploadError(null);

    try {
      const formData = new FormData();

      formData.append("file", selectedFile);
      formData.append("index_for_recall", String(indexForRecall && canIndexForRecall));

      selectedProjectIds.forEach((projectId) => {
        formData.append("project_ids", projectId);
      });

      const res = await fetch("/api/assets/upload", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => null);
        throw new Error(errorData?.detail || `Upload failed: HTTP ${res.status}`);
      }

      await res.json().catch(() => null);

      if (onUploaded) {
        await onUploaded();
      }

      onClose();
    } catch (e) {
      console.error(e);
      setUploadError(e.message || "Upload failed.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
      <div className="w-full max-w-2xl overflow-hidden rounded-xl border border-zinc-700 bg-[#11111f] shadow-2xl shadow-black/60">
        <div className="flex items-start justify-between border-b border-zinc-800 px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-zinc-50">Upload Asset</h2>
            <p className="mt-1 text-sm text-zinc-400">
              Store a file as a first-class MemoryMuse asset. Project assignment is optional.
            </p>
          </div>

          <button
            type="button"
            onClick={onClose}
            disabled={uploading}
            className="rounded-md p-1 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <X size={20} />
          </button>
        </div>

        <div className="space-y-5 px-5 py-5">
          <div>
            <div className="mb-2 text-sm font-medium text-zinc-200">File</div>

            <div
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              className={`flex min-h-[150px] flex-col items-center justify-center rounded-xl border border-dashed px-5 py-6 text-center transition ${
                dragActive
                  ? "border-violet-400 bg-violet-950/30"
                  : "border-zinc-700 bg-[#0d0d18] hover:border-violet-500/50"
              }`}
            >
              <Upload
                size={30}
                className={dragActive ? "text-violet-200" : "text-zinc-500"}
              />

              <div className="mt-3 text-sm text-zinc-300">
                Drop a file here, or choose one from disk.
              </div>

              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="mt-4 rounded-md border border-violet-500/40 px-4 py-2 text-sm font-medium text-violet-200 transition hover:bg-violet-950/40 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Choose File
              </button>

              <input
                ref={fileInputRef}
                type="file"
                onChange={handleFileInputChange}
                className="hidden"
              />

              {selectedFile && (
                <div className="mt-4 max-w-full rounded-md border border-zinc-700 bg-zinc-950/70 px-3 py-2 text-left text-xs text-zinc-300">
                  <div className="truncate font-medium text-zinc-100">
                    {selectedFile.name}
                  </div>
                  <div className="mt-1 text-zinc-500">
                    {selectedFile.type || "unknown type"} ·{" "}
                    {humanFileSize(selectedFile.size)}
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="rounded-lg border border-zinc-800 bg-[#0d0d18] p-4">
            <label className="flex items-start gap-3">
              <input
                type="checkbox"
                checked={indexForRecall}
                disabled={!canIndexForRecall || uploading}
                onChange={(e) => setIndexForRecall(e.target.checked)}
                className="mt-1"
              />

              <div>
                <div
                  className={
                    canIndexForRecall
                      ? "text-sm font-medium text-zinc-100"
                      : "text-sm font-medium text-zinc-500"
                  }
                >
                  Index for recall
                </div>

                <div className="mt-1 text-xs text-zinc-500">
                  {selectedFile
                    ? canIndexForRecall
                      ? "This .txt or .md file can be chunked for semantic recall."
                      : "Only .txt and .md files can be indexed for recall right now."
                    : "Choose a .txt or .md file to enable recall indexing."}
                </div>
              </div>
            </label>
          </div>

          <div>
            <div className="mb-2 text-sm font-medium text-zinc-200">
              Attach to projects
            </div>

            <select
              multiple
              value={selectedProjectIds}
              onChange={handleProjectSelection}
              disabled={projectsLoading || uploading}
              className="min-h-[140px] w-full rounded-md border border-zinc-700 bg-[#16162a] px-3 py-2 text-sm text-zinc-100 outline-none transition focus:border-violet-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {activeProjects.map((project) => {
                const projectId = getProjectId(project);

                if (!projectId) return null;

                return (
                  <option key={projectId} value={projectId}>
                    {getProjectName(project)}
                  </option>
                );
              })}
            </select>

            <div className="mt-2 text-xs text-zinc-500">
              Empty selection is valid: the asset will be general/unscoped.
              {projectsLoading ? " Loading projects…" : ""}
            </div>
          </div>

          {uploadError && (
            <div className="rounded-md border border-red-900/70 bg-red-950/30 px-3 py-2 text-sm text-red-200">
              {uploadError}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-zinc-800 px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            disabled={uploading}
            className="rounded-md border border-zinc-700 px-4 py-2 text-sm text-zinc-300 transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Cancel
          </button>

          <button
            type="button"
            onClick={handleUpload}
            disabled={!selectedFile || uploading}
            className="inline-flex items-center gap-2 rounded-md border border-violet-500/50 bg-violet-950/40 px-4 py-2 text-sm font-medium text-violet-100 transition hover:bg-violet-900/50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {uploading ? (
              <LoaderCircle size={16} className="animate-spin" />
            ) : (
              <Upload size={16} />
            )}
            {uploading ? "Uploading…" : "Upload"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AssetCard({ asset }) {
  const assetId = normalizeAssetId(asset);
  const displayName = getAssetDisplayName(asset);
  const sourceType = getSourceType(asset);
  const assetType = getAssetType(asset);
  const lifecycleStatus = getLifecycleStatus(asset);
  const projectIds = normalizeProjectIds(asset);
  const size = getAssetSize(asset);
  const createdAt = getCreatedAt(asset);

  const thumbnailUrl = getAssetContentUrl(asset, "thumbnail");
  const openUrl = getAssetContentUrl(asset, "display");
  const downloadUrl = getAssetContentUrl(asset, "original", true);

  return (
    <div className="group flex min-h-[320px] flex-col overflow-hidden rounded-xl border border-zinc-800 bg-[#11111f] shadow-lg shadow-black/20 transition hover:border-violet-500/50 hover:bg-[#151526]">
      <div className="relative flex h-44 items-center justify-center overflow-hidden border-b border-zinc-800 bg-black/30">
        {isImageAsset(asset) ? (
          <img
            src={thumbnailUrl}
            alt={displayName}
            className="h-full w-full object-cover transition duration-200 group-hover:scale-[1.02]"
            loading="lazy"
            onError={(e) => {
              e.currentTarget.style.display = "none";
            }}
          />
        ) : (
          <div className="flex flex-col items-center gap-3 text-zinc-400">
            <AssetTypeIcon asset={asset} />
            <span className="text-xs uppercase tracking-widest text-zinc-500">
              {assetType}
            </span>
          </div>
        )}

        <div className="absolute left-3 top-3 flex flex-wrap gap-1">
          <StatusChip tone={sourceTone(sourceType)}>{sourceType}</StatusChip>
          <StatusChip tone={lifecycleTone(lifecycleStatus)}>
            {lifecycleStatus}
          </StatusChip>
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-3 p-4">
        <div>
          <div
            className="line-clamp-2 break-words text-sm font-semibold text-zinc-100"
            title={displayName}
          >
            {displayName}
          </div>

          <div className="mt-1 text-xs text-zinc-500" title={assetId}>
            {assetId || "No asset id"}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 text-xs text-zinc-400">
          <div>
            <div className="text-zinc-600">Type</div>
            <div className="truncate">{asset?.mimetype || assetType}</div>
          </div>

          <div>
            <div className="text-zinc-600">Size</div>
            <div>{humanFileSize(size)}</div>
          </div>

          <div>
            <div className="text-zinc-600">Projects</div>
            <div>{projectIds.length}</div>
          </div>

          <div>
            <div className="text-zinc-600">Created</div>
            <div title={formatDate(createdAt)}>
              {createdAt ? formatDate(createdAt) : "—"}
            </div>
          </div>
        </div>

        {projectIds.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {projectIds.slice(0, 3).map((pid) => (
              <StatusChip key={pid} tone="neutral" title={pid}>
                <FolderKanban size={11} />
                {pid.slice(-6)}
              </StatusChip>
            ))}

            {projectIds.length > 3 && (
              <StatusChip tone="neutral">+{projectIds.length - 3}</StatusChip>
            )}
          </div>
        )}

        <div className="mt-auto flex flex-wrap gap-2 border-t border-zinc-800 pt-3">
          <a
            href={openUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-md border border-violet-500/40 px-2.5 py-1 text-xs text-violet-200 transition hover:bg-violet-950/40"
          >
            <Eye size={13} />
            Open
          </a>

          <a
            href={downloadUrl}
            className="inline-flex items-center gap-1 rounded-md border border-zinc-700 px-2.5 py-1 text-xs text-zinc-300 transition hover:bg-zinc-800"
          >
            <Download size={13} />
            Download
          </a>

          <button
            type="button"
            disabled
            title="Stub: lifecycle editing comes after PATCH endpoint"
            className="inline-flex cursor-not-allowed items-center gap-1 rounded-md border border-zinc-800 px-2.5 py-1 text-xs text-zinc-600"
          >
            <Clock size={13} />
            Lifecycle
          </button>

          <button
            type="button"
            disabled
            title="Stub: rename/edit metadata comes after PATCH endpoint"
            className="inline-flex cursor-not-allowed items-center gap-1 rounded-md border border-zinc-800 px-2.5 py-1 text-xs text-zinc-600"
          >
            <Pencil size={13} />
            Edit
          </button>

          <button
            type="button"
            disabled
            title="Stub: delete comes after DELETE endpoint"
            className="inline-flex cursor-not-allowed items-center gap-1 rounded-md border border-zinc-800 px-2.5 py-1 text-xs text-zinc-600"
          >
            <Trash2 size={13} />
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

export default function FilesManager() {
  const [assets, setAssets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const { uiStates, loading: uiStatesLoading, userConfig } = useConfig();

  const [projects, setProjects] = useState([]);
  const [projectsLoading, setProjectsLoading] = useState(false);

  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [filesStateHydrated, setFilesStateHydrated] = useState(false);
  const [sourceType, setSourceType] = useState("");

  const [assetType, setAssetType] = useState("");
  const [lifecycleStatus, setLifecycleStatus] = useState("available");
  const [projectMode, setProjectMode] = useState("");
  const [searchText, setSearchText] = useState("");
  const [orderBy, setOrderBy] = useState("newest");

  useEffect(() => {
    if (uiStatesLoading) return;

    const saved = uiStates?.files || {};

    setSourceType(saved.source_type || "");
    setAssetType(saved.asset_type || "");
    setLifecycleStatus(saved.lifecycle_status || "available");
    setOrderBy(saved.order_by || "newest");

    setFilesStateHydrated(true);
  }, [uiStatesLoading, uiStates]);

  const fetchProjects = useCallback(async () => {
    setProjectsLoading(true);

    try {
      const res = await fetch("/api/projects");

      if (!res.ok) {
        throw new Error(`Failed to load projects: HTTP ${res.status}`);
      }

      const data = await res.json();
      setProjects(data.projects || []);
    } catch (e) {
      console.error(e);
      setProjects([]);
    } finally {
      setProjectsLoading(false);
    }
  }, []);

  const fetchAssets = useCallback(async ({ quiet = false } = {}) => {
    if (quiet) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    setError(null);

    try {
      const params = new URLSearchParams();

      if (sourceType) params.set("source_type", sourceType);
      if (assetType) params.set("asset_type", assetType);
      if (lifecycleStatus) params.set("lifecycle_status", lifecycleStatus);
      if (projectMode) params.set("project_mode", projectMode);

      params.set("limit", "200");
      params.set("skip", "0");

      const query = params.toString();
      const res = await fetch(`/api/assets/${query ? `?${query}` : ""}`);

      if (!res.ok) {
        throw new Error(`Failed to load assets: HTTP ${res.status}`);
      }

      const data = await res.json();

      // Be forgiving while the API shape evolves.
      setAssets(data.assets || data.items || data.results || []);
    } catch (e) {
      console.error(e);
      setError(e.message || "Failed to load assets.");
      setAssets([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [sourceType, assetType, lifecycleStatus, projectMode]);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  useEffect(() => {
    if (!filesStateHydrated) return;

    fetchAssets();
  }, [
    filesStateHydrated,
    sourceType,
    assetType,
    lifecycleStatus,
    orderBy,
  ]);



  const filteredAssets = useMemo(() => {
    const needle = searchText.trim().toLowerCase();

    let result = assets;

    if (needle) {
      result = assets.filter((asset) => {
        const haystack = [
          normalizeAssetId(asset),
          getAssetDisplayName(asset),
          asset?.filename,
          asset?.mimetype,
          getSourceType(asset),
          getAssetType(asset),
          getLifecycleStatus(asset),
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();

        return haystack.includes(needle);
      });
    }

    return sortAssets(result, orderBy);
  }, [assets, searchText, orderBy]);

  const counts = useMemo(() => {
    const result = {
      total: assets.length,
      shown: filteredAssets.length,
      images: assets.filter(isImageAsset).length,
      generated: assets.filter((a) => getSourceType(a) === "generated").length,
      userUploads: assets.filter((a) => getSourceType(a) === "user_upload").length,
      chatUploads: assets.filter((a) => getSourceType(a) === "chat_upload").length,
    };

    return result;
  }, [assets, filteredAssets]);

  const showEmpty = !loading && !error && filteredAssets.length === 0;

  const handleSourceTypeSelect = (value) => {
      setSourceType(value);
      updateFilesState({ source_type: value });
  };
  const handleAssetTypeSelect = (value) => {
      setAssetType(value);
      updateFilesState({ asset_type: value });
  };
  const handleLifecycleStatusSelect = (value) => {
      setLifecycleStatus(value);
      updateFilesState({ lifecycle_status: value });
  };
  const handleOrderBySelect = (value) => {
      setOrderBy(value);
      updateFilesState({ order_by: value });
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#090913] text-zinc-100">
      <UploadAssetDialog
        open={uploadDialogOpen}
        onClose={() => setUploadDialogOpen(false)}
        projects={projects}
        projectsLoading={projectsLoading}
        onUploaded={() => fetchAssets({ quiet: true })}
      />

      <div className="border-b border-zinc-800 bg-[#11111f] px-6 py-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">
              Files
            </h1>
            <p className="mt-1 max-w-3xl text-sm text-zinc-400">
              Browse MemoryMuse assets across uploads, generated media, chat drops,
              and unscoped files. Management controls are stubbed for now; this first
              cut is the global asset gallery.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setUploadDialogOpen(true)}
              className="inline-flex items-center gap-2 rounded-md border border-violet-500/40 px-4 py-2 text-sm font-medium text-violet-200 transition hover:bg-violet-950/40"
            >
              <Upload size={16} />
              Upload Asset
            </button>

            <button
              type="button"
              onClick={() => fetchAssets({ quiet: true })}
              className="inline-flex items-center gap-2 rounded-md border border-zinc-700 px-4 py-2 text-sm text-zinc-200 transition hover:bg-zinc-800"
            >
              <RefreshCw
                size={16}
                className={refreshing ? "animate-spin text-violet-300" : ""}
              />
              Refresh
            </button>
          </div>
        </div>

        <div className="mt-5 flex flex-wrap gap-2 text-xs">
          <StatusChip tone="neutral">Total: {counts.total}</StatusChip>
          <StatusChip tone="violet">Generated: {counts.generated}</StatusChip>
          <StatusChip tone="green">User uploads: {counts.userUploads}</StatusChip>
          <StatusChip tone="amber">Chat uploads: {counts.chatUploads}</StatusChip>
          <StatusChip tone="neutral">Images: {counts.images}</StatusChip>
          {searchText && <StatusChip tone="neutral">Shown: {counts.shown}</StatusChip>}
        </div>
      </div>

      <div className="border-b border-zinc-800 bg-[#0d0d18] px-6 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[260px] flex-1">
            <Search
              size={16}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500"
            />
            <input
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              placeholder="Search files..."
              className="w-full rounded-md border border-zinc-700 bg-[#16162a] py-2 pl-9 pr-3 text-sm text-zinc-100 outline-none transition placeholder:text-zinc-600 focus:border-violet-500"
            />
          </div>

          <div className="flex items-center gap-2 text-zinc-500">
            <SlidersHorizontal size={16} />
            <span className="text-xs uppercase tracking-wider">Filters</span>
          </div>

          <select
            value={sourceType}
            onChange={(e) => handleSourceTypeSelect(e.target.value)}
            className="rounded-md border border-zinc-700 bg-[#16162a] px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500"
          >
            <option value="">All Sources</option>
            <option value="user_upload">User Uploads</option>
            <option value="chat_upload">Chat Uploads</option>
            <option value="generated">Generated</option>
            <option value="tts_cache">TTS Cache</option>
            <option value="derived">Derived</option>
          </select>

          <select
            value={assetType}
            onChange={(e) => handleAssetTypeSelect(e.target.value)}
            className="rounded-md border border-zinc-700 bg-[#16162a] px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500"
          >
            <option value="">All Types</option>
            <option value="image">Images</option>
            <option value="text">Text</option>
            <option value="pdf">PDF</option>
            <option value="audio">Audio</option>
            <option value="video">Video</option>
            <option value="file">Files</option>
          </select>

          <select
            value={lifecycleStatus}
            onChange={(e) => handleLifecycleStatusSelect(e.target.value)}
            className="rounded-md border border-zinc-700 bg-[#16162a] px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500"
          >
            <option value="">All Lifecycle</option>
            <option value="available">Available</option>
            <option value="expired">Expired</option>
            <option value="deleted">Deleted</option>
            <option value="missing">Missing</option>
            <option value="purged">Purged</option>
          </select>

          <select
            value={projectMode}
            onChange={(e) => setProjectMode(e.target.value)}
            className="rounded-md border border-zinc-700 bg-[#16162a] px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500"
          >
            <option value="">All Project States</option>
            <option value="unscoped">Unscoped</option>
            <option value="attached">Attached to Project</option>
          </select>

          <select
            value={orderBy}
            onChange={(e) => handleOrderBySelect(e.target.value)}
            className="rounded-md border border-zinc-700 bg-[#16162a] px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500"
          >
            <option value="newest">Newest First</option>
            <option value="oldest">Oldest First</option>
            <option value="name_asc">Name A-Z</option>
            <option value="name_desc">Name Z-A</option>
            <option value="size_desc">Largest First</option>
            <option value="size_asc">Smallest First</option>
          </select>
        </div>
      </div>

      <main className="min-h-0 flex-1 overflow-y-auto p-6 pb-24">
        {loading || error || showEmpty ? (
          <EmptyState loading={loading} error={error} />
        ) : (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {filteredAssets.map((asset) => (
              <AssetCard key={normalizeAssetId(asset)} asset={asset} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}