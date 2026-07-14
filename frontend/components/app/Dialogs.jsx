// components/Dialogs.jsx
import React from "react";
import { LoaderCircle, ChevronRight, ChevronDown } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogClose,
} from "@/components/ui/dialog";

function Spinner({ size = 24 }) {
  return <LoaderCircle className="animate-spin text-violet-400" size={size} />;
}


//--- Shared: BaseDialogContent for DRYness ---
export function BaseDialogContent({
  open,
  onOpenChange,
  minWidth = 420,
  maxWidth = 680,
  title,
  headerProps,
  children,
  footer,
  style = {},
  ...rest
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        style={{
          minWidth,
          maxWidth,
          width: "96vw",
          background: "#181846",
          color: "#ebeafd",
          borderRadius: 10,
          boxShadow: "0 6px 32px #000d",
          padding: 0,
          overflow: "auto",
          ...style,
        }}
        {...rest}
      >
        <header
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 14,
            padding: "18px 28px 10px 28px",
            borderBottom: "1.5px solid #282860",
            background: "#181846",
            ...headerProps,
          }}
        >
          <DialogTitle
            style={{
              fontWeight: 700,
              fontSize: 18,
              letterSpacing: 0.10,
              color: "#f3f4fa",
              flex: 1,
              minWidth: 0,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis"
            }}
          >
            {title}
          </DialogTitle>
          {/* DialogClose asChild gives you the X if you want it */}
        </header>
        <div style={{ padding: "20px 28px 10px 28px", fontSize: 15, color: "#bebee3" }}>
          {children}
        </div>
        {footer && (
          <footer
            style={{
              display: "flex",
              justifyContent: "flex-end",
              gap: 10,
              padding: "0 28px 18px 28px"
            }}
          >
            {footer}
          </footer>
        )}
      </DialogContent>
    </Dialog>
  );
}

//--- Detach File Dialog ---
export function DetachDialog({ open, onClose, file, onDetach }) {
  return (
    <BaseDialogContent
      open={open}
      onOpenChange={onClose}
      minWidth={320}
      maxWidth={420}
      title="Detach File?"
      footer={[
        <button
          key="cancel"
          onClick={onClose}
          className="px-3 py-1 border border-violet-300 rounded-md text-violet-300
            bg-transparent font-medium hover:bg-violet-950/20 transition outline-none
            cursor-pointer select-none"
        >
          Cancel
        </button>,
        <button
          key="detach"
          onClick={onDetach}
          className="px-3 py-1 border border-red-400 rounded-md text-red-200
            bg-transparent font-medium hover:bg-red-900/25 transition outline-none
            cursor-pointer select-none"
          style={{ fontWeight: 600 }}
        >
          Detach
        </button>,
      ]}
    >
      <div style={{ marginBottom: 10 }}>
        Are you sure you want to detach <b>{file?.name}</b> from this project?
      </div>
      <div style={{ fontSize: 14, color: "#a6a4c6", marginBottom: 18 }}>
        If this is the only project this file is attached to, it will become available in general conversation.<br />
        <b>To permanently delete the file, use the Delete button instead.</b>
      </div>
    </BaseDialogContent>
  );
}

//--- Delete Asset Dialog ---
export function DeleteDialog({ open, onClose, asset, onDelete }) {
  return (
    <BaseDialogContent
      open={open}
      onOpenChange={onClose}
      minWidth={320}
      maxWidth={420}
      title="Delete File?"
      footer={[
        <button
          key="cancel"
          onClick={onClose}
          className="px-3 py-1 border border-violet-300 rounded-md text-violet-300
            bg-transparent font-medium hover:bg-violet-950/20 transition outline-none
            cursor-pointer select-none"
        >
          Cancel
        </button>,
        <button
          key="delete"
          onClick={onDelete}
          className="px-3 py-1 border border-red-400 rounded-md text-red-200
            bg-transparent font-medium hover:bg-red-900/25 transition outline-none
            cursor-pointer select-none"
          style={{ fontWeight: 600 }}
        >
          Delete
        </button>,
      ]}
    >
      <div style={{ marginBottom: 10 }}>
        Are you sure you want to delete <b>{asset?.filename}</b>?
      </div>
      <div style={{ fontSize: 14, color: "#a6a4c6", marginBottom: 18 }}>
        <br />This file will be removed from all projects and locations.<br /><br />
        <i>After you delete it here, your Muse will immediately lose access to its contents.</i><br /><br />
        <b>This is not permanent.</b> The file will be moved to the <b>Recycle Bin</b>, where you can choose to permanently erase it or restore it later.
      </div>
    </BaseDialogContent>
  );
}


//--- Attach File Dialog ---
export function AttachDialog({
  open,
  onOpenChange,
  loading,
  files = [],
  projectId,
  projects,
  onAttach,
  fetchUnlinkedFiles,
  getProjectName,
  humanFileSize,
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        style={{
          maxWidth: 680,
          minWidth: 480,
          width: "98vw",
          maxHeight: "82vh",
          background: "#181846",
          color: "#ebeafd",
          borderRadius: 10,
          boxShadow: "0 6px 32px #000d",
          padding: 0,
          overflow: "auto",
        }}
      >
        <header
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 14,
            padding: "18px 28px 10px 28px",
            borderBottom: "1.5px solid #282860",
            background: "#181846",
          }}
        >
          <DialogTitle style={{
            fontWeight: 700,
            fontSize: 20,
            letterSpacing: 0.12,
            color: "#f3f4fa",
            flex: 1,
            minWidth: 0,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis"
          }}>
            Attach Existing File
          </DialogTitle>
        </header>
        <div
          style={{
            padding: "14px 22px 14px 22px",
            maxHeight: "62vh",
            overflowY: "auto",
            minHeight: 60,
            width: "100%"
          }}
        >
          {loading ? (
            <div style={{ color: "#bbb", textAlign: "center", padding: 32 }}>
              <Spinner size={20} /> Loading files…
            </div>
          ) : files.length === 0 ? (
            <div style={{ color: "#bbb", textAlign: "center", padding: 32 }}>
              No available files to attach.
            </div>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0, width: "100%" }}>
              {files.map(file => (
                <li
                  key={file.id}
                  style={{
                    padding: "5.5px 0",
                    borderBottom: "1px solid #282860",
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    fontSize: 15,
                    width: "100%"
                  }}
                >
                  <span style={{
                    flex: 2.4,
                    minWidth: 0,
                    whiteSpace: "nowrap",
                    overflow: "visible",
                    textOverflow: "ellipsis",
                    fontWeight: 600
                  }}>
                    {file.name}
                    <span style={{
                      color: "#a9a7bb",
                      marginLeft: 8,
                      fontWeight: 400,
                      fontSize: "0.96em"
                    }}>
                      ({file.mimetype})
                    </span>
                  </span>
                  <span style={{
                    flex: 1,
                    color: "#8886aa",
                    fontSize: "0.96em",
                    textAlign: "right",
                  }}>
                    {humanFileSize(file.size)}
                  </span>
                  <span style={{
                    flex: 1,
                    color: "#9998c7",
                    fontSize: "0.96em",
                    textAlign: "right",
                    minWidth: 120
                  }}>
                    {file.uploaded_on ? new Date(file.uploaded_on).toLocaleString() : "—"}
                  </span>
                  <span style={{ flex: 1, fontSize: "0.91em", minWidth: 80 }}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      {file.project_ids
                        .filter(pid => pid !== projectId)
                        .map(pid => (
                          <span
                            key={pid}
                            style={{
                              background: "#a78bfa22",
                              color: "#a78bfa",
                              borderRadius: 4,
                              padding: "2px 7px",
                              margin: "1px 0",
                              fontWeight: 500,
                              fontSize: "0.86em",
                              whiteSpace: "nowrap",
                              overflow: "visible",
                              display: "inline-block"
                            }}
                          >
                            {getProjectName(projects, pid)}
                          </span>
                        ))}
                    </div>
                  </span>
                  <button
                    onClick={() => onAttach(file)}
                    className="px-2.5 py-1 border border-violet-400 rounded-md text-violet-200
                      bg-transparent font-medium hover:bg-violet-950/30 transition outline-none
                      cursor-pointer select-none"
                    style={{
                      marginLeft: 8,
                      fontSize: 14,
                      boxShadow: "none"
                    }}
                    tabIndex={0}
                  >
                    Attach
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

//--- View File Dialog ---
export function ViewFileDialog({
  open,
  onClose,
  file,
  fileContent,
  projectId,
  getDisplayType,
  getFileUrl,
}) {
  if (!file) return null;
  const displayType = getDisplayType(file);
  const fileUrl = getFileUrl(file);
  return (
    <Dialog open={open} onOpenChange={onClose}>
        <DialogContent
          style={{
            minWidth: displayType === "text" ? 600 : 360,   // Text gets wide by default, images can start smaller
            maxWidth: "60vw",
            minHeight: 360,
            maxHeight: "80vh",
            background: "#181846",
            color: "#ddd",
            borderRadius: 12,
            boxShadow: "0 4px 24px #000a",
            display: "flex",
            flexDirection: "column",   // Ensures header/content layout
            alignItems: "stretch"
          }}
        >
        <DialogHeader>
          <DialogTitle>
            {file?.name ?? "File Viewer"}
          </DialogTitle>
        </DialogHeader>
        <DialogClose />
        {(() => {
          switch (displayType) {
            case "text":
              return (
                <pre
                  style={{
                    maxHeight: "calc(80vh - 120px)",
                    minHeight: 400,
                    overflow: "auto",
                    background: "#222244",
                    color: "#eee",
                    fontSize: 15,
                    borderRadius: 8,
                    padding: 18,
                    margin: 0,
                    whiteSpace: "pre-wrap",           // This enables wrapping!
                    wordBreak: "break-word"           // Long words won't bust the box
                  }}
                >
                  {fileContent ?? "Loading..."}
                </pre>
              );
            case "image":
              return (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    width: "100%",
                    minHeight: 320,
                    maxHeight: 440,
                    overflowY: "auto",           // Scroll if image + caption exceed maxHeight
                    padding: "1.5em 0"
                  }}
                >
                  <img
                    src={fileUrl}
                    alt={file.name}
                    style={{
                      maxWidth: "72vw",
                      maxHeight: 340,             // Generous image height (adjust as needed)
                      width: "auto",
                      height: "auto",
                      borderRadius: 8,
                      background: "#222",
                      boxShadow: "0 2px 16px #0004",
                      display: "block"
                    }}
                  />
                  <div
                    style={{
                      marginTop: 16,
                      maxWidth: "68vw",
                      color: "#b6b3d6",
                      fontSize: 15.5,
                      lineHeight: 1.45,
                      fontStyle: "italic",
                      textAlign: "center",
                      padding: "6px 18px 0 18px",
                      wordBreak: "break-word",
                      background: "none",
                      width: "100%"
                    }}
                  >
                    {file?.caption
                      ? file.caption
                      : <span style={{ color: "#888" }}>[No caption]</span>
                    }
                  </div>
                </div>
              );
            case "pdf":
              return (
                <object
                  data={fileUrl}
                  type="application/pdf"
                  width="100%"
                  height="400px"
                  style={{ borderRadius: 8, background: "#222" }}
                >
                  <a href={fileUrl} download>Download PDF</a>
                </object>
              );
            case "audio":
              return (
                <audio controls style={{ width: "100%" }}>
                  <source src={fileUrl} type={file.mimetype} />
                  Your browser does not support the audio element.
                </audio>
              );
            case "video":
              return (
                <video controls width="100%" style={{ maxHeight: 400, borderRadius: 8, background: "#222" }}>
                  <source src={fileUrl} type={file.mimetype} />
                  Your browser does not support the video tag.
                </video>
              );
            default:
              return (
                <div>
                  <p>{file.name}</p>
                  <a href={fileUrl} download>
                    Download
                  </a>
                  <p style={{ color: "#888" }}>Preview not supported.</p>
                </div>
              );
          }
        })()}
      </DialogContent>
    </Dialog>
  );
}

// (You can add DeleteDialog, UpdateDialog, etc. here as needed)