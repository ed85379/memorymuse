import React, { useEffect, useRef, useState } from "react";
import {
  Pencil,
  FolderKanban,
  Eye,
  Download,
  Clock,
  Trash2,
} from "lucide-react";
import {
  DeleteDialog,
} from "@/components/app/Dialogs";

function getAssetContentUrl(asset, variant = "original", download = false) {
  const assetId = normalizeAssetId(asset);
  if (!assetId) return "#";

  const params = new URLSearchParams();

  if (variant) params.set("variant", variant);
  if (download) params.set("download", "true");

  const query = params.toString();
  return `/api/assets/${assetId}/content${query ? `?${query}` : ""}`;
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

function formatDate(value) {
  if (!value) return "—";

  try {
    return new Date(value).toLocaleString();
  } catch {
    return "—";
  }
}

function formatOptionalDate(value) {
  return value ? formatDate(value) : "—";
}

export default function AssetCard({
    asset,
    projects,
    onPatched,
    onDeleted,
    normalizeAssetId,
    getAssetDisplayName,
    getSourceType,
    getAssetType,
    getLifecycleStatus,
    normalizeProjectIds,
    getAssetSize,
    getCreatedAt,
    getAssetContentUrl,
    getDescription,
    getDescriptionPreview,
    isImageAsset,
    AssetTypeIcon,
    StatusChip,
    humanFileSize,
    getProjectId,
    getProjectName,
  }) {
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

  const description = getDescription(asset);
  const descriptionPreview = getDescriptionPreview(description);
  const lifecycle = asset?.lifecycle || {};
  const activeProjects = (projects || []).filter((project) => !project.archived);

  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(displayName);

  const [editingDescription, setEditingDescription] = useState(false);
  const [descriptionDraft, setDescriptionDraft] = useState(description);

  const [projectDraft, setProjectDraft] = useState(projectIds);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);

  useEffect(() => {
    setNameDraft(displayName);
    setDescriptionDraft(description);
    setProjectDraft(projectIds);
  }, [assetId, displayName, description, projectIds.join("|")]);

  const savePatch = async (patch) => {
    if (!assetId || saving) return null;

    setSaving(true);
    setSaveError(null);

    try {
      const res = await fetch(`/api/assets/${assetId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(patch),
      });

      const data = await res.json().catch(() => null);

      if (!res.ok) {
        throw new Error(data?.detail || `Failed to update asset: HTTP ${res.status}`);
      }

      if (!data?.asset) {
        throw new Error("Asset update succeeded, but returned no asset.");
      }

      onPatched?.(data.asset);
      return data.asset;
    } catch (error) {
      console.error(error);
      setSaveError(error.message || "Failed to update asset.");
      return null;
    } finally {
      setSaving(false);
    }
  };

  const handleSaveName = async () => {
    const nextName = nameDraft.trim();

    if (!nextName || nextName === displayName) {
      setNameDraft(displayName);
      setEditingName(false);
      return;
    }

    const updated = await savePatch({ display_name: nextName });

    if (updated) {
      setEditingName(false);
    }
  };

  const handleSaveDescription = async () => {
    const nextDescription = descriptionDraft.trim();

    if (nextDescription === description) {
      setEditingDescription(false);
      return;
    }

    const updated = await savePatch({
      description: nextDescription || null,
    });

    if (updated) {
      setEditingDescription(false);
    }
  };

  const toggleProjectDraft = (projectId) => {
    setProjectDraft((currentIds) =>
      currentIds.includes(projectId)
        ? currentIds.filter((id) => id !== projectId)
        : [...currentIds, projectId]
    );
  };

  const handleSaveProjects = async () => {
    await savePatch({ project_ids: projectDraft });
  };

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deletingAsset, setDeletingAsset] = useState(null);

  const handleDeleteOpen = (asset) => {
    setDeletingAsset(asset);
    setDeleteDialogOpen(true);
  };

  const handleDeleteConfirm = async () => {
    if (!deletingAsset) return;

    const assetId = normalizeAssetId(deletingAsset);

    if (!assetId) {
      console.error("Cannot delete asset with no asset ID:", deletingAsset);
      return;
    }

    const res = await fetch(`/api/assets/${assetId}`, {
      method: "DELETE",
    });

    if (!res.ok) {
      throw new Error(`Failed to delete asset: HTTP ${res.status}`);
    }

    setDeleteDialogOpen(false);
    setDeletingAsset(null);

    await onDeleted?.();
  };


  return (
    <div className="group relative flex min-h-[320px] flex-col rounded-xl border border-zinc-800 bg-[#11111f] shadow-lg shadow-black/20 transition hover:border-violet-500/50 hover:bg-[#151526]">
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
          {editingName ? (
            <div className="space-y-2">
              <input
                autoFocus
                value={nameDraft}
                onChange={(event) => setNameDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") handleSaveName();
                  if (event.key === "Escape") {
                    setNameDraft(displayName);
                    setEditingName(false);
                  }
                }}
                className="w-full rounded-md border border-violet-500/50 bg-[#0d0d18] px-2 py-1.5 text-sm font-semibold text-zinc-100 outline-none focus:border-violet-400"
              />

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleSaveName}
                  disabled={saving}
                  className="rounded-md border border-violet-500/50 px-2 py-1 text-xs text-violet-200 hover:bg-violet-950/40 disabled:opacity-50"
                >
                  Save
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setNameDraft(displayName);
                    setEditingName(false);
                  }}
                  disabled={saving}
                  className="rounded-md border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-start gap-2">
              <div
                className="min-w-0 flex-1 line-clamp-2 break-words text-sm font-semibold text-zinc-100"
                title={displayName}
              >
                {displayName}
              </div>

              <button
                type="button"
                onClick={() => setEditingName(true)}
                title="Rename asset"
                className="shrink-0 text-zinc-500 transition hover:text-violet-200"
              >
                <Pencil size={14} />
              </button>
            </div>
          )}

          <div className="mt-1 text-xs text-zinc-500" title={assetId}>
            {assetId || "No asset id"}
          </div>
        </div>
        <div className="rounded-md border border-zinc-800 bg-black/10 px-3 py-2">
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-zinc-500">Description</span>

            {!editingDescription && (
              <button
                type="button"
                onClick={() => setEditingDescription(true)}
                className="text-xs text-zinc-500 transition hover:text-violet-200"
              >
                {description ? "Edit" : "Add"}
              </button>
            )}
          </div>

          {editingDescription ? (
            <div className="space-y-2">
              <textarea
                autoFocus
                value={descriptionDraft}
                onChange={(event) => setDescriptionDraft(event.target.value)}
                rows={4}
                placeholder="Describe this asset for future recall and image use…"
                className="w-full resize-y rounded-md border border-violet-500/50 bg-[#0d0d18] px-2 py-1.5 text-sm text-zinc-100 outline-none placeholder:text-zinc-600 focus:border-violet-400"
              />

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleSaveDescription}
                  disabled={saving}
                  className="rounded-md border border-violet-500/50 px-2 py-1 text-xs text-violet-200 hover:bg-violet-950/40 disabled:opacity-50"
                >
                  Save
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setDescriptionDraft(description);
                    setEditingDescription(false);
                  }}
                  disabled={saving}
                  className="rounded-md border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : descriptionPreview ? (
            <div className="text-sm text-zinc-300">
              <div className="line-clamp-1">{descriptionPreview}</div>

              {description !== descriptionPreview && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-xs text-violet-300 hover:text-violet-200">
                    Read more
                  </summary>

                  <div className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-zinc-300">
                    {description}
                  </div>
                </details>
              )}
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setEditingDescription(true)}
              className="text-left text-sm italic text-zinc-600 transition hover:text-violet-200"
            >
              — Add a description
            </button>
          )}
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

        <details className="relative">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-md border border-zinc-700 px-2.5 py-1 text-xs text-zinc-300 transition hover:bg-zinc-800">
            <FolderKanban size={13} />
            {projectIds.length === 0
              ? "No projects"
              : `${projectIds.length} project${projectIds.length === 1 ? "" : "s"}`}
          </summary>

          <div className="absolute left-0 top-full z-30 mt-2 w-72 rounded-lg border border-zinc-700 bg-[#161625] p-3 shadow-2xl shadow-black/50">
            <div className="mb-2 text-xs font-medium text-zinc-300">Projects</div>

            <div className="max-h-48 space-y-1 overflow-y-auto">
              {activeProjects.map((project) => {
                const projectId = getProjectId(project);
                if (!projectId) return null;

                return (
                  <label
                    key={projectId}
                    className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm text-zinc-300 hover:bg-zinc-800"
                  >
                    <input
                      type="checkbox"
                      checked={projectDraft.includes(projectId)}
                      onChange={() => toggleProjectDraft(projectId)}
                      disabled={saving}
                    />
                    <span className="truncate">{getProjectName(project)}</span>
                  </label>
                );
              })}
            </div>

            <div className="mt-3 flex justify-end gap-2 border-t border-zinc-800 pt-3">
              <button
                type="button"
                onClick={() => setProjectDraft(projectIds)}
                disabled={saving}
                className="rounded-md border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-50"
              >
                Reset
              </button>

              <button
                type="button"
                onClick={handleSaveProjects}
                disabled={saving}
                className="rounded-md border border-violet-500/50 px-2 py-1 text-xs text-violet-200 hover:bg-violet-950/40 disabled:opacity-50"
              >
                Save projects
              </button>
            </div>
          </div>
        </details>
        {saveError && (
          <div className="rounded-md border border-red-900/70 bg-red-950/30 px-2 py-1.5 text-xs text-red-200">
            {saveError}
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

          <details className="relative">
            <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-md border border-zinc-700 px-2.5 py-1 text-xs text-zinc-300 transition hover:bg-zinc-800">
              <Clock size={13} />
              Lifecycle
            </summary>

            <div className="absolute bottom-full right-0 z-30 mb-2 w-72 rounded-lg border border-zinc-700 bg-[#161625] p-3 shadow-2xl shadow-black/50">
              <div className="mb-3 text-xs font-medium text-zinc-300">Lifecycle</div>

              <dl className="space-y-1.5 text-xs">
                <div className="flex justify-between gap-3">
                  <dt className="text-zinc-500">Status</dt>
                  <dd className="text-zinc-200">{lifecycleStatus}</dd>
                </div>

                <div className="flex justify-between gap-3">
                  <dt className="text-zinc-500">Created</dt>
                  <dd className="text-right text-zinc-200">
                    {formatOptionalDate(lifecycle.created_at || createdAt)}
                  </dd>
                </div>

                <div className="flex justify-between gap-3">
                  <dt className="text-zinc-500">Expires</dt>
                  <dd className="text-right text-zinc-200">
                    {formatOptionalDate(lifecycle.expires_at)}
                  </dd>
                </div>

                <div className="flex justify-between gap-3">
                  <dt className="text-zinc-500">Purge after</dt>
                  <dd className="text-right text-zinc-200">
                    {formatOptionalDate(lifecycle.purge_after)}
                  </dd>
                </div>
              </dl>

              <label className="mt-3 flex cursor-pointer items-start gap-2 border-t border-zinc-800 pt-3 text-sm text-zinc-300">
                <input
                  type="checkbox"
                  checked={Boolean(lifecycle.permanent)}
                  disabled={saving}
                  onChange={(event) => savePatch({ permanent: event.target.checked })}
                />

                <span>
                  <span className="block">Permanent</span>
                  <span className="block text-xs text-zinc-500">
                    Protect this asset from ordinary cleanup.
                  </span>
                </span>
              </label>
            </div>
          </details>

          <details className="relative">
            <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-md border border-zinc-700 px-2.5 py-1 text-xs text-zinc-300 transition hover:bg-zinc-800">
              <Pencil size={13} />
              Options
            </summary>

            <div className="absolute bottom-full right-0 z-30 mb-2 w-72 rounded-lg border border-zinc-700 bg-[#161625] p-3 shadow-2xl shadow-black/50">
              <div className="mb-3 text-xs font-medium text-zinc-300">Asset options</div>

              {isImageAsset(asset) && (
                <label className="flex cursor-pointer items-start gap-2 text-sm text-zinc-300">
                  <input
                    type="checkbox"
                    checked={Boolean(asset?.image_source_enabled)}
                    disabled={saving}
                    onChange={(event) =>
                      savePatch({ image_source_enabled: event.target.checked })
                    }
                  />

                  <span>
                    <span className="block">Enable as image source</span>
                    <span className="block text-xs text-zinc-500">
                      Makes this image available as a selectable image-work reference.
                    </span>
                  </span>
                </label>
              )}

              <label className="mt-3 flex cursor-pointer items-start gap-2 text-sm text-zinc-300">
                <input
                  type="checkbox"
                  checked={Boolean(asset?.injection_enabled)}
                  disabled={saving}
                  onChange={(event) =>
                    savePatch({ injection_enabled: event.target.checked })
                  }
                />

                <span>
                  <span className="block">Allow prompt injection</span>
                  <span className="block text-xs text-zinc-500">
                    Makes this asset available for deliberate current-turn context.
                  </span>
                </span>
              </label>
            </div>
          </details>

          <button
            type="button"
            onClick={() => handleDeleteOpen(asset)}

            title="Stub: delete comes after DELETE endpoint"
            className="inline-flex items-center gap-1 rounded-md border border-zinc-700 px-2.5 py-1 text-xs text-zinc-300 transition hover:bg-zinc-800"
          >
            <Trash2 size={13} />
            Delete
          </button>
        </div>
      </div>
      <DeleteDialog
        open={deleteDialogOpen}
        onClose={() => {
          setDeleteDialogOpen(false);
          setDeletingAsset(null);
        }}
        asset={deletingAsset}
        onDelete={handleDeleteConfirm}
      />
    </div>
  );
}