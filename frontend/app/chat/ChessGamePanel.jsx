"use client";

import React from "react";
import { Chessboard } from "react-chessboard";
import {
  ChessKnight,
  RefreshCw,
} from "lucide-react";


function getTurnLabel(fen) {
  if (!fen || typeof fen !== "string") {
    return null;
  }

  const activeColor = fen.split(/\s+/)[1];

  if (activeColor === "w") {
    return "White to move";
  }

  if (activeColor === "b") {
    return "Black to move";
  }

  return null;
}


const ChessGamePanel = ({
  open,
  onClose,
  game,
  loading = false,
  error = null,
  onRefresh,
}) => {
  if (!open) return null;

  const fen =
    game?.state?.fen ||
    game?.context_display?.fen ||
    null;

  const musePlan =
    game?.state?.muse_plan ??
    game?.context_display?.muse_plan ??
    null;

  const turnLabel = getTurnLabel(fen);

  const lastMove =
    game?.last_turn?.result?.notation ||
    game?.last_turn?.result?.move ||
    null;

  const chessboardOptions = {
    position: fen,
    allowDragging: false,

    boardStyle: {
      borderRadius: "10px",
      overflow: "hidden",
      border:
        "2px solid rgba(192, 132, 252, 0.45)",
      boxShadow:
        "0 0 0 1px rgba(255,255,255,0.05), " +
        "0 16px 38px rgba(0,0,0,0.6)",
    },

    lightSquareStyle: {
      backgroundColor: "#d8c6a3",
    },

    darkSquareStyle: {
      backgroundColor: "#5c3d62",
    },
  };

  return (
    <aside
      className="
        fixed right-0 top-0 z-50
        flex h-dvh w-full max-w-[440px] flex-col
        border-l border-purple-400/30
        bg-neutral-950
        shadow-2xl
        animate-in slide-in-from-right
        duration-200
      "
    >
      <div className="flex items-center justify-between border-b border-neutral-800 px-4 py-3">
        <div className="flex min-w-0 items-start gap-2">
          <ChessKnight className="mt-0.5 h-5 w-5 shrink-0 text-purple-300" />

          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-purple-100">
              {game?.label || "Chess with Iris"}
            </div>

            <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-neutral-400">
              {turnLabel && <span>{turnLabel}</span>}

              {game && (
                <span>
                  Revision {game.revision ?? 0}
                </span>
              )}

              {game?.status === "archived" && (
                <span className="text-amber-300">
                  Archived
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1">
          {onRefresh && (
            <button
              type="button"
              onClick={onRefresh}
              disabled={loading}
              className="
                flex h-8 w-8 items-center justify-center
                rounded-md text-neutral-400
                hover:bg-neutral-800
                hover:text-white
                disabled:opacity-50
              "
              title="Reload canonical game state"
            >
              <RefreshCw
                className={`h-4 w-4 ${
                  loading ? "animate-spin" : ""
                }`}
              />
            </button>
          )}

          <button
            type="button"
            onClick={onClose}
            aria-label="Close chess board"
            title="Fold away board"
            className="
              flex h-8 w-8 items-center justify-center
              rounded-md text-xl leading-none
              text-neutral-300
              hover:bg-neutral-800
              hover:text-white
              transition
            "
          >
            ×
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {loading && !game ? (
          <div className="flex min-h-64 items-center justify-center text-sm text-neutral-400">
            Loading game table…
          </div>
        ) : error ? (
          <div className="rounded-xl border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-200">
            {error}
          </div>
        ) : !fen ? (
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4 text-sm text-neutral-400">
            This game has no renderable chess position.
          </div>
        ) : (
          <>
            <div className="mx-auto w-full max-w-[390px]">
              <Chessboard
                options={chessboardOptions}
              />
            </div>

            <div className="mt-5 grid grid-cols-2 gap-3">
              <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-3">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-neutral-500">
                  Last move
                </div>

                <div className="mt-1 text-sm text-neutral-200">
                  {lastMove || "No moves yet"}
                </div>
              </div>

              <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-3">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-neutral-500">
                  Status
                </div>

                <div className="mt-1 text-sm capitalize text-neutral-200">
                  {game?.status || "active"}
                </div>
              </div>
            </div>


            <div className="mt-4 rounded-xl border border-neutral-800 bg-neutral-900/60 p-3 text-xs leading-relaxed text-neutral-500">
              This table is now loaded from the durable game
              document. Local move drafting and chess.js turn
              preparation remain the next gameplay layer.
            </div>
          </>
        )}
      </div>
    </aside>
  );
};


export default ChessGamePanel;