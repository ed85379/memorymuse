import { useState, useEffect } from "react";
import { RefreshCw, Pin } from 'lucide-react';
import { humanFileSize } from '@/utils/utils';
import { updateUiStateForProject } from "@/utils/statesFunctions";

export default function ProjectsPanel({
  projects,
  project,
  fetchProjects,
  selectedProjectId,
  setSelectedProjectId,
  assetsByProjectId,
  assetsLoading,
  fetchAssets,
  focus,
  setFocus,
  autoAssign,
  setAutoAssign,
  injectedAssets,
  setInjectedAssets,
  handlePinToggle,
  handleAssetPinToggle,
}) {



  // UI handlers
  const handleFocusChange = val => {
    setFocus(val); // keep the UI snappy
    updateUiStateForProject(selectedProjectId, { blend_ratio: val });
  };

  const handleAutoAssignChange = () => {
    setAutoAssign(prev => {
      const next = !prev;
      updateUiStateForProject(selectedProjectId, { auto_assign: next });
      return next;
    });
  };


  const handleAssetInjectToggle = (aid, name) => {
    setInjectedAssets(prev => {
      const exists = prev.find(a => a.id === aid);
      if (exists) {
        return prev.filter(a => a.id !== aid);
      } else {
        return [...prev, { id: aid, name, pinned: false }];
      }
    });
  };

  const isAssetInjected = aid => injectedAssets.some(a => a.id === aid);
  const isAssetPinned = aid => injectedAssets.some(a => a.id === aid && a.pinned);

  return (
    <div className="p-2 text-neutral-200">
      {/* Project Dropdown */}
      <div className="mb-4 flex items-center gap-2">
        <span className="mr-2 font-semibold text-purple-300">Select Project:</span>
        <select
          className="bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm"
          value={selectedProjectId}
          onChange={e => setSelectedProjectId(e.target.value)}
          onFocus={fetchProjects}
        >
          <option value="">(Select...)</option>
          {projects
            .filter(proj => !proj.is_hidden) // Only show non-hidden projects
            .map(proj => (
              <option key={proj._id} value={proj._id}>
                {proj.name}
              </option>
            ))
          }
        </select>
        {/* Note about hidden projects */}
        {projects.filter(proj => proj.is_hidden).length > 0 && (
          <span className="text-xs text-neutral-500">
            ({projects.filter(proj => proj.is_hidden).length} hidden project{projects.filter(proj => proj.is_hidden).length > 1 ? 's' : ''})
          </span>
        )}
      </div>

      {!project && (
        <div className="text-neutral-400">
          Select a project to view files and settings.
        </div>
      )}

      {project && (() => {
        const projectAssets = assetsByProjectId[project._id] || [];

        /*
        const displayedAssets = projectAssets.filter(
          assetFile => assetFile.source_type === "user_upload"
        );
        */
        const displayedAssets = projectAssets

        return (
        <>
        {/* Focus */}
        <div className="mb-4 flex flex-col items-center">
          <div className="text-purple-300 font-semibold mb-1">Focus</div>
          <div className="flex items-center gap-2">
            <span className="text-neutral-400 text-xs w-10 text-right">Global</span>
            <input
              type="range"
              min={0.5}
              max={1}
              step={0.1}
              value={focus}
              onChange={e => handleFocusChange(Number(e.target.value))}
              className="accent-purple-500 flex-1"
              style={{ width: 120 }}
            />
            <span className="text-neutral-400 text-xs w-10">Project</span>
          </div>
        </div>

        {/* Auto-assign */}
        <div className="mb-4 flex items-center gap-2">
          <input
            type="checkbox"
            checked={autoAssign}
            onChange={handleAutoAssignChange}
            className="accent-purple-500"
            id="autoAssignToggle"
          />
          <label
            htmlFor="autoAssignToggle"
            className="text-purple-300 font-semibold select-none cursor-pointer"
          >
            Auto-assign messages to this project
          </label>
        </div>

        {/* Files in project */}
        <div className="mb-4">
          <div className="flex items-center mb-2 font-semibold text-purple-300">
            <span>Files in Project:</span>
            {
              assetsLoading ? (
                <svg className="ml-2 animate-spin h-5 w-5 text-purple-400" /* ...spinner SVG... */ />
            ) : (
            <button
              type="button"
              className="ml-2 p-1 rounded hover:bg-neutral-800 transition-colors"
              title="Refresh file list"
              onClick={fetchAssets}
              aria-label="Refresh file list"
            >
              <RefreshCw size={18} className="text-purple-400 hover:rotate-90 transition-transform" />
            </button>
            )
          }
          </div>
          <ul className="mt-3 space-y-1 border-t border-neutral-800 pt-3">
            {displayedAssets.map(assetFile => {
              const injected = isAssetInjected(assetFile.id);
              const pinned = isAssetPinned(assetFile.id);

              return (
                <li key={assetFile.id} className="flex items-center gap-2 text-neutral-200">
                  <span className="flex-1">
                    {assetFile.name}
                    {assetFile.size ? (
                      <span className="ml-2 text-neutral-500 text-xs">
                        {humanFileSize(assetFile.size)}
                      </span>
                    ) : null}
                    <span className="ml-2 rounded bg-purple-900/40 px-1.5 py-0.5 text-[10px] text-purple-200">
                      asset
                    </span>
                  </span>

                  <button
                    className={`px-2 py-0.5 rounded text-xs font-semibold
                      ${injected
                        ? "bg-purple-600 text-purple-100"
                        : "bg-neutral-800 text-purple-300 hover:bg-purple-600 hover:text-purple-100"
                      }`}
                    onClick={() => handleAssetInjectToggle(assetFile.id, assetFile.name)}
                    type="button"
                  >
                    {injected ? "Injected" : "Inject"}
                  </button>

                  <button
                    className={`px-2 py-0.5 rounded text-xs font-semibold flex items-center
                      ${pinned
                        ? "bg-purple-700 text-purple-100 border border-purple-300"
                        : "bg-neutral-700 text-purple-200 hover:bg-purple-600 hover:text-purple-100"
                      }
                      ${!injected ? "opacity-50 cursor-not-allowed" : ""}
                    `}
                    onClick={() => injected && handleAssetPinToggle(assetFile.id)}
                    disabled={!injected}
                    type="button"
                    aria-label={pinned ? `Unpin ${assetFile.name}` : `Pin ${assetFile.name}`}
                    title={pinned ? "Unpin file" : "Pin file"}
                  >
                    <Pin
                      className={`w-4 h-4 ${pinned ? "text-purple-200" : "text-purple-400"}`}
                      strokeWidth={2}
                    />
                  </button>
                </li>
              );
            })}

            {!assetsLoading && displayedAssets.length === 0 && (
              <li className="text-neutral-500">No asset files in this project yet.</li>
            )}
          </ul>
        </div>
        </>
        );
      })()}
    </div>
  );
}