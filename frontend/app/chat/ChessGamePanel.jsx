"use client";

import React from "react";
import { Chessboard } from "react-chessboard";

const DEMO_FEN =
  "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3";

const ChessGamePanel = ({
  open,
  onClose,
  fen = DEMO_FEN,
}) => {
  if (!open) return null;

  const chessboardOptions = {
    position: fen,
    allowDragging: false,

    boardStyle: {
      borderRadius: "10px",
      overflow: "hidden",
      border: "2px solid rgba(192, 132, 252, 0.45)",
      boxShadow:
        "0 0 0 1px rgba(255,255,255,0.05), 0 16px 38px rgba(0,0,0,0.6)",
    },

    lightSquareStyle: { backgroundColor: "#d8c6a3" },
    darkSquareStyle: { backgroundColor: "#5c3d62" },
  };

  return (
    <>



      {/* Actual slide-out game table */}
      <aside
        className="
          fixed right-0 top-0 z-50
          flex h-dvh w-full max-w-[440px] flex-col
          border-l border-purple-400/30
          bg-neutral-950
          shadow-2xl
          animate-in slide-in-from-right duration-200
        "
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-neutral-800 px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-purple-100">
              ♞ Chess with Iris
            </div>
            <div className="mt-0.5 text-xs text-neutral-400">
              Demo board — Black to move
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close chess board"
            title="Close board"
            className="
              flex h-8 w-8 items-center justify-center
              rounded-md text-xl leading-none text-neutral-300
              hover:bg-neutral-800 hover:text-white
              transition
            "
          >
            ×
          </button>
        </div>

        {/* Board */}
        <div className="flex-1 overflow-y-auto p-4">
          <div className="mx-auto w-full max-w-[390px]">
            <Chessboard options={chessboardOptions} />
          </div>

          {/* Intentionally fake, but establishes the future UI seam */}
          <div className="mt-5 rounded-xl border border-purple-400/20 bg-purple-950/25 p-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-purple-300">
              Move draft
            </div>

            <div className="mt-2 text-sm text-neutral-400">
              Select a move on the board, then send it with your table talk.
            </div>

            <div className="mt-3 rounded-lg border border-dashed border-neutral-700 bg-black/20 px-3 py-2 text-sm text-neutral-500">
              No move drafted yet.
            </div>
          </div>

          <div className="mt-4 rounded-xl border border-neutral-800 bg-neutral-900/60 p-3 text-xs leading-relaxed text-neutral-500">
            This is only the visual shell. Next, the board gets its FEN from
            Mongo; after that, it gets local <code>chess.js</code> drafting.
          </div>
        </div>
      </aside>
    </>
  );
};

export default ChessGamePanel;