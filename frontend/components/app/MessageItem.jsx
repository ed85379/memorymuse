"use client";
import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import MessageActions from "./MessageActions";
import TTSController from "./TTSController";
import { BookMarked, EyeOff, MessageCircleHeart, MessageCircleOff } from "lucide-react";

const formatTimestamp = (utcString) => {
  if (!utcString) return "";
  const dt = new Date(utcString);
  return dt.toLocaleString();
};

// --- 1. Split out custom XML-ish blocks ---
function splitCustomBlocks(raw) {
  if (!raw) return [];

  const result = [];
  let lastIndex = 0;

  const regex =
    /<(command-response|muse-(experience|interlude)|gm-note)>([\s\S]*?)<\/\1>/gi;
  let match;

  while ((match = regex.exec(raw)) !== null) {
    const before = raw.slice(lastIndex, match.index);
    if (before) {
      result.push({ type: "markdown", text: before });
    }

    if (match[1] === "command-response") {
      let inner = match[3];
      const internalMatch = inner.match(
        /<internal-data>([\s\S]*?)<\/internal-data>/i
      );
      let visible = inner;
      if (internalMatch) {
        visible = inner.replace(internalMatch[0], "").trim();
      }

      // If nothing is left after removing internal-data, skip this block entirely
      if (!visible) {
        lastIndex = regex.lastIndex;
        continue;
      }

      result.push({ type: "command", text: visible });
    } else if (match[1] === "gm-note") {
      result.push({ type: "gm", text: match[3].trim() });
    } else {
      const museType = match[2]; // "experience" or "interlude"
      result.push({ type: "muse", museType, text: match[3].trim() });
    }


    lastIndex = regex.lastIndex;
  }

  if (lastIndex < raw.length) {
    result.push({ type: "markdown", text: raw.slice(lastIndex) });
  }

  return result;
}

// --- 2. Command + Muse components ---

function CommandResponse({ text }) {
  return (
    <div className="my-1 rounded-md bg-purple-900/50 border border-purple-500/25 px-3 py-2 text-[0.9rem] text-purple-100/90">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

function MuseBlock({ museType, text }) {
  const label =
    museType === "experience" ? "Muse Experience" : "Muse Interlude";
  return (
    <details open className="text-sm text-neutral-300 italic my-4 mt-4">
      <summary className="cursor-pointer select-none text-purple-400">
        {label}
      </summary>
      <div className="mt-0 pl-3 border-l border-neutral-700">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {text}
        </ReactMarkdown>
      </div>
    </details>
  );
}

function GmNote({ gmType, text }) {
  const label = "GM Note";
  return (
    <details className="text-sm text-neutral-300 italic my-4 mt-4">
      <summary className="cursor-pointer select-none text-purple-400">
        {label}
      </summary>
      <div className="mt-0 pl-3 border-l border-neutral-700">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {text}
        </ReactMarkdown>
      </div>
    </details>
  );
}

function MessageAsset({ asset }) {
  if (asset.mimetype?.startsWith("image/")) {
    return <ImageAsset asset={asset} />;
  }

  return <FileAsset asset={asset} />;
}

function ImageAsset({ asset }) {
  const src = `/api/assets/${asset.asset_id}/content`;
  const filename =
    asset.display_name || asset.filename || "attached-image";

  const aspectRatio =
    asset.width && asset.height
      ? `${asset.width} / ${asset.height}`
      : undefined;

  return (
    <figure className="message-image-asset">
      <a
        className="message-image-link"
        href={src}
        target="_blank"
        rel="noopener noreferrer"
        title="Open image in new tab"
      >
        <div
          className="message-image-frame"
          style={{ aspectRatio }}
        >
          <img
            src={src}
            alt={filename}
            loading="lazy"
          />
        </div>
      </a>

      <figcaption className="message-asset-caption">
        <span className="message-asset-name">{filename}</span>

        <span className="message-asset-actions">
          <a
            href={src}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open
          </a>

          <a
            href={src}
            download={filename}
          >
            Download
          </a>
        </span>
      </figcaption>
    </figure>
  );
}

function FileAsset({ asset }) {
  const href = `/api/assets/${asset.asset_id}/content`;

  return (
    <a className="message-file-asset" href={href} download>
      <span className="file-icon">
        {iconForMimetype(asset.mimetype)}
      </span>

      <span className="file-info">
        <span className="file-name">
          {asset.display_name || asset.filename || asset.asset_id}
        </span>

        {asset.size && (
          <span className="file-size">
            {formatBytes(asset.size)}
          </span>
        )}
      </span>
    </a>
  );
}

// --- 3. Main MessageItem ---

const MessageItem = React.memo(
  React.forwardRef(function MessageItemInner(props, ref) {
    const {

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



      onReturnToThisMoment,
      multiSelectEnabled,
      isSelected,
      onToggleSelect,

      setShowSingleThreadPanel,
      setThreadPanelOpen,
      showSingleThreadPanel,
      handleCreateThread,
      handleJoinThread,
      handleLeaveThread,
      clearSelectionAndExit,
    } = props;
  if (!msg) return <div>[No message]</div>;


  const rawText = msg.message || msg.text || "";
  const blocks = splitCustomBlocks(rawText);

  // --- role → bubbleClass / displayName, same logic you had ---

  const effectiveRole = msg.from || msg.role || "";
  let displayName = "Other";
  let bubbleClass = "bg-purple-900 text-white self-start text-left";

  if (effectiveRole === "user") {
    displayName = "You";
    bubbleClass = "bg-neutral-800 text-purple-100 self-end text-left";
  } else if (effectiveRole === "muse" || effectiveRole === "iris") {
    displayName = museName;
    bubbleClass = "bg-purple-950 text-white self-start text-left";
  } else if (effectiveRole === "other" || effectiveRole === "friend") {
    displayName = msg.username ? msg.username : "Friend";
    bubbleClass = "bg-neutral-700 text-white self-start text-left";
  } else if (effectiveRole) {
    displayName = effectiveRole
      .replace(/_/g, " ")
      .replace(/\b\w/g, (l) => l.toUpperCase());
    bubbleClass = "bg-purple-900 text-white self-start text-left";
  }

  const rightAlign = effectiveRole === "user";
  const isPrivate = !!msg.is_private;
  const isHidden = !!msg.is_hidden;
  const isRemembered = !!msg.remembered;
  const isDeleted = !!msg.is_deleted;
  const inProject = msg.project_id;
  const userTags =
    msg.user_tags?.filter(
      (t) =>
        t !== "private" &&
        t !== "hidden" &&
        t !== "deleted" &&
        t !== "remembered"
    ) || [];
  const bubbleWidth = "max-w-[80%]";

  const handleClick = (e) => {
    if (!multiSelectEnabled) return;
    if (e.target?.closest?.("button, a, summary")) return;
    onToggleSelect && onToggleSelect(msg.message_id);
  };

  const headingBase = "font-semibold text-purple-100";

  return (
    <div
      ref={ref}
      className={`space-y-1 flex flex-col ${
        rightAlign ? "items-end" : "items-start"
      }`}
    >
      <div className={`${bubbleWidth} ${rightAlign ? "ml-auto" : ""}`}>
        <div className="text-xs text-neutral-400">{displayName}</div>
        <div className="text-xs text-neutral-500">
          {formatTimestamp(msg.timestamp)}
        </div>

        <div
          className={`relative group text-sm px-3 py-2 rounded-lg whitespace-pre-wrap ${bubbleClass}
            ${
              isSelected && multiSelectEnabled
                ? "ring-2 ring-purple-500 ring-offset-2 ring-offset-neutral-900"
                : ""
            }
          `}
          onClick={handleClick}
        >
          {/* NEW: markdown renderer instead of dangerouslySetInnerHTML */}
          <div className="max-w-none text-sm leading-snug pt-4 pb-6">
            {blocks.map((block, idx) => {
              if (block.type === "markdown") {
                return (
                  <ReactMarkdown
                    key={idx}
                    remarkPlugins={[remarkGfm]}
                    components={{
                      h1: ({ children }) => (
                        <h1 className={`${headingBase} text-lg mt-2 mb-1`}>
                          {children}
                        </h1>
                      ),
                      h2: ({ children }) => (
                        <h2 className={`${headingBase} text-base mt-2 mb-1`}>
                          {children}
                        </h2>
                      ),
                      h3: ({ children }) => (
                        <h3 className={`${headingBase} text-sm mt-2 mb-1`}>
                          {children}
                        </h3>
                      ),
                      h4: ({ children }) => (
                        <h4 className={`${headingBase} text-xs uppercase tracking-wide mt-2 mb-1 text-purple-300`}>
                          {children}
                        </h4>
                      ),
                      table: ({ children }) => (
                        <div className="my-2 overflow-x-auto">
                          <table className="w-full border-collapse text-xs">
                            {children}
                          </table>
                        </div>
                      ),
                      thead: ({ children }) => (
                        <thead className="bg-neutral-900 text-purple-200">
                          {children}
                        </thead>
                      ),
                      th: ({ children }) => (
                        <th className="border border-neutral-700 px-2 py-1 text-left font-semibold">
                          {children}
                        </th>
                      ),
                      td: ({ children }) => (
                        <td className="border border-neutral-800 px-2 py-1 align-top">
                          {children}
                        </td>
                      ),
                      p: ({ node, ...props }) => (
                        <p className="my-0.5" {...props} />
                      ),
                      ul: ({ node, ...props }) => (
                        <ul className="my-0.5 ml-4 list-disc" {...props} />
                      ),
                      ol: ({ node, ...props }) => (
                        <ol className="my-0.5 ml-4 list-decimal" {...props} />
                      ),
                      li: ({ node, ...props }) => (
                        <li className="my-0.5" {...props} />
                      ),
                      blockquote: ({ node, ...props }) => (
                        <blockquote
                          className="my-1 pl-2 border-l border-neutral-700 text-neutral-300 italic"
                          {...props}
                        />
                      ),
                      a: ({ node, ...props }) => (
                        <a
                          {...props}
                          target="_blank"
                          rel="noreferrer"
                          className="text-purple-300 underline hover:text-purple-200"
                        />
                      ),
                      img: ({ node, ...props }) => (
                        <img
                          {...props}
                          className="max-w-full max-h-64 rounded border border-neutral-700"
                        />
                      ),
                      code({ inline, className, children, ...props }) {
                        const text = String(children || "");
                        const hasLanguage = /language-\w+/.test(className || "");

                        // Optional: map short aliases → real languages
                        const langAliasMap = {
                          js: "javascript",
                          ts: "typescript",
                          tsx: "tsx",
                          sh: "bash",
                          shell: "bash",
                        };

                        const match = /language-(\w+)/.exec(className || "");
                        const rawLang = match ? match[1] : "";
                        const language = langAliasMap[rawLang] || rawLang || "plaintext";

                        // 1) True inline code: `like this`
                        if (inline) {
                          return (
                            <code
                              className="bg-[#22172b] text-purple-300 px-[0.15em] py-[0.15em]
                                         rounded-md text-[0.98em] font-mono"
                              {...props}
                            >
                              {children}
                            </code>
                          );
                        }

                        // 2) “Inline-looking” but parsed as block:
                        //    no language, single line → style like inline, still on its own line
                        if (!hasLanguage && !text.includes("\n")) {
                          return (
                            <code
                              className="bg-[#22172b] text-purple-300 px-[0.15em] py-[0.15em]
                                         rounded-md text-[0.98em] font-mono"
                              {...props}
                            >
                              {children}
                            </code>
                          );
                        }

                        // 3) Real fenced blocks: ```js ... ``` → use SyntaxHighlighter
                        const codeString = text.replace(/\n$/, ""); // trim trailing newline react-markdown adds

                        return (
                          <div className="my-1 rounded-md bg-neutral-950/90 border border-neutral-800 overflow-hidden">
                            <div className="flex items-center justify-between px-2 py-1 text-[0.65rem] bg-neutral-900/80 text-neutral-400">
                              <span className="uppercase tracking-wide">
                                {language || "code"}
                              </span>
                              <button
                                type="button"
                                className="px-1.5 py-0.5 rounded bg-neutral-800 text-neutral-200 hover:bg-neutral-700"
                                onClick={async e => {
                                  e.stopPropagation();
                                  try {
                                    await navigator.clipboard.writeText(codeString);
                                    // optional: tiny visual feedback later
                                  } catch (err) {
                                    console.error("Failed to copy code:", err);
                                  }
                                }}
                              >
                                Copy
                              </button>
                            </div>
                            <SyntaxHighlighter
                              style={vscDarkPlus}
                              language={language}
                              PreTag="div"
                              customStyle={{
                                margin: 0,
                                padding: "0.5rem 0.75rem",
                                background: "transparent",
                                fontSize: "0.8rem",
                              }}
                              {...props}
                            >
                              {codeString}
                            </SyntaxHighlighter>
                          </div>
                        );
                      },
                    }}
                  >
                    {block.text}
                  </ReactMarkdown>
                );
              }

              if (block.type === "command") {
                return <CommandResponse key={idx} text={block.text} />;
              }

              if (block.type === "muse") {
                return (
                  <MuseBlock
                    key={idx}
                    museType={block.museType}
                    text={block.text}
                  />
                );
              }

              if (block.type === "gm") {
                return <GmNote key={idx} text={block.text} />;
              }

              return null;
            })}
            {msg.metadata?.assets?.length > 0 && (
              <div className="message-assets">
                {[...msg.metadata.assets]
                  .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
                  .map((asset) => (
                    <MessageAsset key={asset.asset_id} asset={asset} />
                  ))}
              </div>
            )}
          </div>

          <TTSController
            msg={msg}
            audioControls={audioControls}
            effectiveRole={effectiveRole}
            connecting={connecting}
          />
          <MessageActions
            msg={msg}
            setMessages={setMessages}
            setThreadMessages={setThreadMessages}
            setAltMessages={setAltMessages}
            projects={projects}
            projectsLoading={projectsLoading}
            tagDialogOpen={tagDialogOpen}
            setTagDialogOpen={setTagDialogOpen}
            projectDialogOpen={projectDialogOpen}
            setProjectDialogOpen={setProjectDialogOpen}
            mode={mode}
            onReturnToThisMoment={onReturnToThisMoment}
            multiSelectEnabled={multiSelectEnabled}
            isSelected={isSelected}
            onToggleSelect={onToggleSelect}
            threads={threads}
            setShowSingleThreadPanel={setShowSingleThreadPanel}
            setThreadPanelOpen={setThreadPanelOpen}
            showSingleThreadPanel={showSingleThreadPanel}
            handleCreateThread={handleCreateThread}
            handleJoinThread={handleJoinThread}
            handleLeaveThread={handleLeaveThread}
            clearSelectionAndExit={clearSelectionAndExit}
          />
        </div>

        <div className="flex flex-wrap gap-1 mt-1 ml-2">
          {inProject && projectMap.projects[inProject] && (
            <span className="bg-purple-800 text-xs text-purple-100 px-2 py-0.5 rounded-full flex items-center gap-1">
              <BookMarked size={14} className="inline" />
              <span className="font-semibold">
                {projectMap.projects[inProject].name || "Project"}
              </span>
            </span>
          )}
          {userTags.map((tag) => (
            <span
              key={tag}
              className="bg-purple-800 text-xs text-purple-100 px-2 py-0.5 rounded-full"
            >
              #{tag}
            </span>
          ))}
          {isRemembered && (
            <span className="bg-neutral-700 text-xs text-purple-300 px-2 py-0.5 rounded-full flex items-center gap-1">
              <MessageCircleHeart size={14} className="inline" /> Highlighted
            </span>
          )}
          {isPrivate && (
            <span className="bg-neutral-700 text-xs text-purple-300 px-2 py-0.5 rounded-full flex items-center gap-1">
              <EyeOff size={14} className="inline" /> Private
            </span>
          )}
          {isHidden && (
            <span className="bg-neutral-700 text-xs text-purple-300 px-2 py-0.5 rounded-full flex items-center gap-1">
              <EyeOff size={14} className="inline" /> Hidden
            </span>
          )}
          {isDeleted && (
            <span className="bg-neutral-700 text-xs text-purple-300 px-2 py-0.5 rounded-full flex items-center gap-1">
              <MessageCircleOff size={14} className="inline" /> Forgotten
            </span>
          )}
        </div>
      </div>
    </div>
  );
}));

export default MessageItem;