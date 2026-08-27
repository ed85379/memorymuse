"use client";
import React, {useEffect, useState, useMemo} from "react";
import { useFeatures } from '@/hooks/FeaturesContext';
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import {Eye, EyeOff, DoorClosed, DoorClosedLocked, SquarePlus, SquarePen, Archive, ArchiveX} from 'lucide-react';
import ProjectDetailsCard from "./ProjectDetailsCard";
import ProjectFacts from "./ProjectFacts";



const TABS = [
  {key: "details", label: "Details"},
  {key: "facts", label: "Facts"},
];

const MAX_LENGTH_NAME = 40;
const MAX_LENGTH_DESC = 512;
const MAX_LENGTH_NOTE = 256;
const MAX_LENGTH_TAG = 24;

const EyeIcon = ({is_hidden}) => (
  is_hidden
    ? <span title="Hidden from muse" style={{color: "#ef4444", fontSize: 20, marginLeft: 6}}><EyeOff
      size={32}/></span>
    :
    <span title="Accessible to muse" style={{color: "#22c55e", fontSize: 20, marginLeft: 6}}><Eye size={32}/></span>
);
const DoorIcon = ({is_private}) => (
  is_private
    ? <span title="Will not show in public spaces" style={{color: "#ef4444", fontSize: 20, marginLeft: 6}}><DoorClosedLocked
      size={32}/></span>
    :
    <span title="Available everywhere" style={{color: "#22c55e", fontSize: 20, marginLeft: 6}}><DoorClosed size={32}/></span>
);
const ArchiveIcon = ({archived}) => (
  archived
    ? <span title="Archived" style={{color: "#ef4444", fontSize: 20, marginLeft: 6}}><ArchiveX size={32}/></span>
    : <span title="Live" style={{color: "#22c55e", fontSize: 20, marginLeft: 6}}><Archive size={32}/></span>
);

const CodeIntensitySelector = ({ value, onChange }) => {
  const current = value || "mixed";

  const optionStyle = (opt) => ({
    display: "flex",
    alignItems: "center",
    gap: 2,
    padding: "2px 4px",
    borderRadius: 4,
    background: current === opt ? "#1f2937" : "transparent",
  });

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "6px 10px",
        borderRadius: 8,
        background: "#111827",
        border: "1px solid #374151",
        minWidth: 140, // keeps it compact but readable
      }}
    >
      <span
        style={{
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: 0.08,
          color: "#9ca3af",
          fontWeight: 600,
        }}
      >
        Code intensity
      </span>

      <RadioGroup
        value={current}
        onValueChange={onChange}
        className="flex flex-col gap-1"
      >
        <div style={optionStyle("NOCODE")}>
          <RadioGroupItem value="NOCODE" id="code-none" className="h-3 w-3" />
          <Label htmlFor="code-none" style={{ fontSize: 11, color: "#e5e7eb" }}>
            None
          </Label>
        </div>

        <div style={optionStyle("MIXED")}>
          <RadioGroupItem value="MIXED" id="code-mixed" className="h-3 w-3" />
          <Label htmlFor="code-mixed" style={{ fontSize: 11, color: "#e5e7eb" }}>
            Mixed
          </Label>
        </div>

        <div style={optionStyle("HEAVYCODE")}>
          <RadioGroupItem value="HEAVYCODE" id="code-heavy" className="h-3 w-3" />
          <Label htmlFor="code-heavy" style={{ fontSize: 11, color: "#e5e7eb" }}>
            Heavy
          </Label>
        </div>
      </RadioGroup>
    </div>
  );
};

const ToggleVisibilityButton = ({is_hidden, onToggle, loading}) => (
  <button
    className="toggle-btn"
    onClick={onToggle}
    disabled={loading}
    style={{
      background: is_hidden ? "#ef444433" : "#22c55e33",
      color: is_hidden ? "#ef4444" : "#22c55e",
      border: "1px solid",
      borderColor: is_hidden ? "#ef4444" : "#22c55e",
      borderRadius: 7,
      padding: "5px 14px",
      fontWeight: "bold",
      marginLeft: 10,
      fontSize: 12,
      cursor: loading ? "wait" : "pointer"
    }}
    title={is_hidden
      ? "Show this project to your muse (and allow it to be processed by OpenAI)"
      : "Hide this project from your muse and OpenAI"}
  >
    {loading
      ? "…"
      : is_hidden ? "Show Project" : "Hide Project"}
  </button>
);

const TogglePrivacyButton = ({is_private, onToggle, loading}) => (
  <button
    className="toggle-btn"
    onClick={onToggle}
    disabled={loading}
    style={{
      background: is_private ? "#a855f733" : "#22c55e33",
      color: is_private ? "#a855f7" : "#22c55e",
      border: "1px solid",
      borderColor: is_private ? "#a855f7" : "#22c55e",
      borderRadius: 7,
      padding: "5px 14px",
      fontWeight: "bold",
      marginLeft: 10,
      fontSize: 12,
      cursor: loading ? "wait" : "pointer"
    }}
    title={is_private
      ? "Let these messages be available to your muse in public spaces"
      : "Hide these memories from your muse in public spces"}
  >
    {loading
      ? "…"
      : is_private ? "Set Public" : "Set Private"}
  </button>
);

const ToggleArchivedButton = ({archived, onToggle, loading}) => (
  <button
    className="toggle-btn"
    onClick={onToggle}
    disabled={loading}
    style={{
      background: archived ? "#ef444433" : "#22c55e33",
      color: archived ? "#ef4444" : "#22c55e",
      border: "1px solid",
      borderColor: archived ? "#ef4444" : "#22c55e",
      borderRadius: 7,
      padding: "5px 14px",
      fontWeight: "bold",
      marginLeft: 10,
      fontSize: 12,
      cursor: loading ? "wait" : "pointer"
    }}
  title={archived
    ? "Show this project to your muse."
    : "Hide this project from your muse and the list."}
  >
  {loading
    ? "…"
    : archived ? "Unarchive Project" : "Archive Project"}
  </button>
);

const getBorderColor = (project) => {
  if (project.is_hidden) return "#ef4444";
  if (project.is_private) return "#a855f7";
  return "#22c55e";
};

export default function ProjectCard(props) {
  const {projects, project, onToggleVisibility, onTogglePrivacy, onToggleArchived, toggleLoading, onProjectChange, ...rest} = props;
  const borderColor = getBorderColor(project);
  const [editing, setEditing] = useState({name: false});
  const [draft, setDraft] = useState({
    name: project.name
  });
  const [uploadPercent, setUploadPercent] = useState(0);
  const [isProcessing, setIsProcessing] = useState(false);
  const [lastUploadedFileId, setLastUploadedFileId] = useState(null);
  const [tab, setTab] = useState("details");

  const { adminConfig, adminLoading } = useFeatures();
  const mm = adminConfig?.mm_features || {};
  const enablePublic = !!mm.ENABLE_PUBLIC_INTERFACES ;

  // Only reset local state when switching projects (not on every save/edit)
  useEffect(() => {
    setEditing({name: false});
    setDraft({
      name: project.name
    });
  }, [project._id]);

  // Save handlers
  const handleSave = (field) => {
    onProjectChange({[field]: draft[field]});
    setEditing(e => ({...e, [field]: false}));
  };

  const handleEdit = (field) => setEditing(e => ({...e, [field]: true}));


  return (
    <div
      className="project-card-outer"
      style={{
        background: "#23233a",
        borderRadius: 8,
        boxShadow: "0 2px 16px #0001",
        padding: 0,
        margin: "0 auto",
        width: "100%",
        maxWidth: 1080,
        border: `1.5px solid ${borderColor}`,
        transition: "border-color 0.2s",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* --- Header --- */}
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 20,
          padding: "18px 28px 10px 28px",
          borderBottom: "1px solid #282860",
          background: "#23233a",
        }}
      >
      <div style={{
        flex: 1,
        minWidth: 0,
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}>
        <span
          style={{
            color: "#b2b2c8", // Muted, non-distracting
            fontWeight: 500,
            fontSize: 16,
            textTransform: "uppercase",
            letterSpacing: 0.1,
            marginRight: 6,
            flexShrink: 0,
            opacity: 0.85
          }}
        >
          Project:
        </span>
          {editing.name ? (
            <form
              onSubmit={e => {
                e.preventDefault();
                handleSave("name");
              }}
              style={{width: "100%"}}
            >
            <input
              type="text"
              value={draft.name}
              onChange={e => setDraft(d => ({...d, name: e.target.value}))}
              maxLength={MAX_LENGTH_NAME}
              autoFocus
              style={{
                fontSize: 20,
                background: "none",
                color: "#fff",
                border: draft.name.length > MAX_LENGTH_NAME ? "2px solid #f55" : "1px solid #444",
                borderRadius: 5,
                outline: "none",
                width: "100%",
                padding: "3px 10px",
                fontWeight: 700,
                letterSpacing: 0.2,
              }}
              onBlur={() => handleSave("name")}
            />
            </form>
          ) : (
            <>
              <>
                <span
                  style={{
                    fontWeight: 700,
                    fontSize: 20,
                    color: "#f3f4fa",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    maxWidth: 320,
                    letterSpacing: 0.2,
                  }}
                  title={project.name}
                >
                  {project.name}
                </span>
              </>
                <SquarePen
                  size={18}
                  strokeWidth={1.5}
                  onClick={() => handleEdit("name")}
                  style={{cursor: "pointer", marginLeft: 10, color: "#b9a8fc"}}
                  title="Rename project"
                />
            </>
          )}
      </div>
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
      }}>
        <ToggleArchivedButton
          archived={project.archived}
          onToggle={onToggleArchived}
          loading={toggleLoading}
        />
        <ArchiveIcon archived={project.archived}/>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <ToggleVisibilityButton
            is_hidden={project.is_hidden}
            onToggle={onToggleVisibility}
            loading={toggleLoading}
          />
          <EyeIcon is_hidden={project.is_hidden} />
          {enablePublic && (
          <>
          <TogglePrivacyButton
            is_private={project.is_private}
            onToggle={onTogglePrivacy}
            loading={toggleLoading}
          />
          <DoorIcon is_private={project.is_private} />
          </>
          )}
        </div>

        <CodeIntensitySelector
          value={project.code_intensity}
          onChange={(newValue) => {
            console.log("Code intensity change:", newValue);
            if (props.onProjectChange) {
              props.onProjectChange({ code_intensity: newValue });
            }
          }}
        />
        </div>
      </header>

      {/* --- Tabs --- */}
      <div className="flex gap-2 border-b border-neutral-800"
         style={{
           padding: "0 22px",
           background: "#23233a"
         }}
      >
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-t ${tab === t.key
              ? "bg-neutral-950 text-purple-400 font-bold border-b-2 border-purple-500"
              : "bg-neutral-900 text-neutral-400 hover:text-white"
            }`}
            style={{
              transition: "background 0.18s",
              fontSize: 15,
              fontWeight: tab === t.key ? 700 : 500,
              letterSpacing: 0.1,
              marginBottom: "-1px" // subtle lift for active tab
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* --- Tab content --- */}
      <div
        className="p-4 bg-neutral-950 rounded-b-lg"
        style={{
          minHeight: 180,
          padding: "24px 28px 36px 28px"
        }}
      >
        {tab === "details" && (
          <ProjectDetailsCard
            project={project}
            onProjectChange={props.onProjectChange}
            {...rest}
          />
        )}
        {tab === "facts" && (
          <ProjectFacts project={project} {...rest} />
        )}
      </div>
    </div>
  );
}

const cardBtnStyle = {
  borderRadius: 7,
  background: "#292950",
  color: "#fff",
  border: "1px solid #343468",
  padding: "7px 18px",
  fontSize: 15,
  cursor: "pointer",
  fontWeight: 500
};
const miniBtnStyle = {
  ...cardBtnStyle,
  padding: "3px 13px",
  fontSize: 13,
  marginRight: 8,
  background: "#181823"
};

