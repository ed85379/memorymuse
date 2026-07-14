"use client";
import { useState, useEffect, useRef } from "react";
import ProjectsPanel from "./ProjectsPanel";
import { useConfig } from '@/hooks/ConfigContext';
import { updateNavState } from "@/utils/statesFunctions";


const TABS = [
  { key: "projects", label: "Projects" },
  { key: "muse", label: "Muse" },
  { key: "games", label: "Games" },
  { key: "files", label: "Files" }
];

// Helper for pretty file sizes
function humanFileSize(bytes) {
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

export default function TabbedToolPanel(
  {
    projects,
    project,
    fetchProjects,
    projectMap,
    selectedProjectId,
    setSelectedProjectId,
    assetsByProjectId,
    assetsLoading,
    fetchAssets,
    focus,
    setFocus,
    autoAssign,
    setAutoAssign,
    injectedFiles,
    setInjectedFiles,
    setInjectedAssets,
    injectedAssets,
    files,
    fetchFiles,
    filesLoading,
    setFilesLoading,
    filesError,
    handlePinToggle,
    handleAssetPinToggle,
    threads,
    threadMap,
  }
) {
  const { uiStates } = useConfig();
  const [activeTab, setActiveTab] = useState("projects");

  useEffect(() => {
    if (uiStates?.nav?.tools_panel_tab) {
      setActiveTab(uiStates.nav.tools_panel_tab);
    }
  }, [uiStates]);

  return (
    <div className="flex flex-col bg-neutral-950 rounded-b-xl shadow-inner overflow-hidden h-full">
      <div className="flex gap-1 border-b border-neutral-800 bg-neutral-900/80 px-2">
      {TABS.map(tab => (
        <button
          key={tab.key}
          className={`px-3 py-2 text-sm rounded-t-md font-semibold transition
            ${activeTab === tab.key
              ? 'text-purple-200 bg-neutral-900 border-b-2 border-purple-700'
              : 'text-purple-400 hover:bg-neutral-800/70'
            }`
          }
          onClick={() => {
            setActiveTab(tab.key);
            updateNavState({ tools_panel_tab: tab.key });
          }}
          tabIndex={0}
        >
          {tab.label}
        </button>
      ))}
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {activeTab === "projects" && (
          <ProjectsPanel
            projects={projects}
            project={project}
            fetchProjects={fetchProjects}
            projectMap={projectMap}
            selectedProjectId={selectedProjectId}
            setSelectedProjectId={setSelectedProjectId}
            assetsByProjectId={assetsByProjectId}
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
            files={files}
            fetchFiles={fetchFiles}
            filesLoading={filesLoading}
            setFilesLoading={setFilesLoading}
            filesError={filesError}
            handlePinToggle={handlePinToggle}
            handleAssetPinToggle={handleAssetPinToggle}
          />
        )}
        {activeTab === "threads" && (
          <div>
            {/* Placeholder content */}
            <p className="text-neutral-300">Threads.</p>
          </div>
        )}
        {activeTab === "muse" && (
          <div>
            {/* Placeholder content */}
            <p className="text-neutral-300">Muse info/tools go here.</p>
          </div>
        )}
        {activeTab === "games" && (
          <div>
            <p className="text-neutral-300">Game tools including RP</p>
          </div>
        )}
        {activeTab === "files" && (
          <div>
            <p className="text-neutral-300">Files and uploads will live here.</p>
          </div>
        )}
      </div>
    </div>
  );
}