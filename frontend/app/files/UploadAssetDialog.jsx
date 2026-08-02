import React, { useEffect, useRef, useState } from "react";
import {
  LoaderCircle,
  Upload,
  X,
} from "lucide-react";

function isIndexableTextFile(file) {
  if (!file?.name) return false;
  return /\.(txt|md)$/i.test(file.name);
}

export default function UploadAssetDialog({
  open,
  onClose,
  projects,
  projectsLoading,
  onUploaded,
  getProjectId,
  getProjectName,
  humanFileSize,
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