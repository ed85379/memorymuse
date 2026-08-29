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
  Pencil,
  Upload,
  X,
} from "lucide-react";
import { useConfig } from '@/hooks/ConfigContext';
import { updateFilesState } from "@/utils/statesFunctions";
import UploadAssetDialog from "./UploadAssetDialog";
import AssetCard from "./AssetCard";

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

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



function getDescription(asset) {
  return String(asset?.description || "").trim();
}

function getDescriptionPreview(description) {
  return description
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean) || "";
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
  const [lifecycleStatus, setLifecycleStatus] = useState("");
  const [projectMode, setProjectMode] = useState("");
  const [searchText, setSearchText] = useState("");
  const [orderBy, setOrderBy] = useState("newest");
  const [pageSize, setPageSize] = useState(25);
  const [currentPage, setCurrentPage] = useState(1);


  useEffect(() => {
    if (uiStatesLoading) return;

    const saved = uiStates?.files || {};
    const savedPageSize = Number(saved.page_size);

    setSourceType(saved.source_type || "");
    setAssetType(saved.asset_type || "");
    setLifecycleStatus(saved.lifecycle_status || "available");
    setProjectMode(saved.project_mode || "");
    setOrderBy(saved.order_by || "newest");
    setPageSize(
      PAGE_SIZE_OPTIONS.includes(savedPageSize) ? savedPageSize : 25
    );

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
      const res = await fetch("/api/assets/");

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
  }, []);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  useEffect(() => {
    if (!filesStateHydrated) return;
    fetchAssets();
  }, [filesStateHydrated, fetchAssets]);


  const filteredAssets = useMemo(() => {
    const needle = searchText.trim().toLowerCase();

    const result = assets.filter((asset) => {
      if (sourceType && getSourceType(asset) !== sourceType) {
        return false;
      }

      if (assetType && getAssetType(asset) !== assetType) {
        return false;
      }

      if (
        lifecycleStatus &&
        getLifecycleStatus(asset) !== lifecycleStatus
      ) {
        return false;
      }

      const projectIds = normalizeProjectIds(asset);

      if (projectMode === "unscoped" && projectIds.length > 0) {
        return false;
      }

      if (projectMode === "attached" && projectIds.length === 0) {
        return false;
      }

      if (!needle) {
        return true;
      }

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

    return sortAssets(result, orderBy);
  }, [
    assets,
    sourceType,
    assetType,
    lifecycleStatus,
    projectMode,
    searchText,
    orderBy,
  ]);

  const pageCount = Math.max(
    1,
    Math.ceil(filteredAssets.length / pageSize)
  );

  const activePage = Math.min(currentPage, pageCount);

  const pageStart = (activePage - 1) * pageSize;

  const pagedAssets = useMemo(
    () => filteredAssets.slice(pageStart, pageStart + pageSize),
    [filteredAssets, pageStart, pageSize]
  );

  const visibleFrom = filteredAssets.length ? pageStart + 1 : 0;

  const visibleTo = Math.min(
    pageStart + pageSize,
    filteredAssets.length
  );

  useEffect(() => {
    setCurrentPage(1);
  }, [
    sourceType,
    assetType,
    lifecycleStatus,
    projectMode,
    searchText,
    orderBy,
    pageSize,
  ]);

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

  const handleProjectModeSelect = (value) => {
    setProjectMode(value);
    updateFilesState({ project_mode: value });
  };

  const handlePageSizeSelect = (value) => {
    const nextPageSize = Number(value);

    if (!PAGE_SIZE_OPTIONS.includes(nextPageSize)) {
      return;
    }

    setPageSize(nextPageSize);
    updateFilesState({ page_size: nextPageSize });
  };

  const handleAssetPatched = useCallback((updatedAsset) => {
    const updatedAssetId = normalizeAssetId(updatedAsset);

    if (!updatedAssetId) {
      console.warn("PATCH returned an asset with no usable asset ID:", updatedAsset);
      return;
    }

    setAssets((currentAssets) =>
      currentAssets.map((asset) =>
        normalizeAssetId(asset) === updatedAssetId
          ? { ...asset, ...updatedAsset }
          : asset
      )
    );
  }, []);

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#090913] text-zinc-100">
      <UploadAssetDialog
        open={uploadDialogOpen}
        onClose={() => setUploadDialogOpen(false)}
        projects={projects}
        projectsLoading={projectsLoading}
        onUploaded={() => fetchAssets({ quiet: true })}
        getProjectId={getProjectId}
        getProjectName={getProjectName}
        humanFileSize={humanFileSize}
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
          {counts.shown !== counts.total && (
            <StatusChip tone="neutral">
              Matching: {counts.shown}
            </StatusChip>
          )}
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
            onChange={(e) => handleProjectModeSelect(e.target.value)}
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
          <label className="flex items-center gap-2 text-xs text-zinc-500">
            <span className="whitespace-nowrap uppercase tracking-wider">
              Per page
            </span>

            <select
              value={pageSize}
              onChange={(e) => handlePageSizeSelect(e.target.value)}
              className="rounded-md border border-zinc-700 bg-[#16162a] px-3 py-2 text-sm text-zinc-100 outline-none focus:border-violet-500"
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <main className="min-h-0 flex-1 overflow-y-auto p-6 pb-24">
        {loading || error || showEmpty ? (
          <EmptyState loading={loading} error={error} />
        ) : (
          <>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {pagedAssets.map((asset) => (
              <AssetCard
                key={normalizeAssetId(asset)}
                asset={asset}
                projects={projects}
                onPatched={handleAssetPatched}
                onDeleted={() => fetchAssets({ quiet: true })}
                normalizeAssetId={normalizeAssetId}
                getAssetDisplayName={getAssetDisplayName}
                getSourceType={getSourceType}
                getAssetType={getAssetType}
                getLifecycleStatus={getLifecycleStatus}
                normalizeProjectIds={normalizeProjectIds}
                getAssetSize={getAssetSize}
                getCreatedAt={getCreatedAt}
                getAssetContentUrl={getAssetContentUrl}
                getDescription={getDescription}
                getDescriptionPreview={getDescriptionPreview}
                isImageAsset={isImageAsset}
                AssetTypeIcon={AssetTypeIcon}
                StatusChip={StatusChip}
                humanFileSize={humanFileSize}
                getProjectId={getProjectId}
                getProjectName={getProjectName}
              />
            ))}
          </div>
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-zinc-800 pt-4">
            <div className="text-sm text-zinc-500">
              Showing {visibleFrom}–{visibleTo} of {filteredAssets.length}
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                disabled={activePage <= 1}
                className="rounded-md border border-zinc-700 px-3 py-1.5 text-sm text-zinc-300 transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Previous
              </button>

              <span className="min-w-24 text-center text-sm text-zinc-400">
                Page {activePage} of {pageCount}
              </span>

              <button
                type="button"
                onClick={() =>
                  setCurrentPage((page) => Math.min(pageCount, page + 1))
                }
                disabled={activePage >= pageCount}
                className="rounded-md border border-zinc-700 px-3 py-1.5 text-sm text-zinc-300 transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
          </>
        )}
      </main>

    </div>
  );
}