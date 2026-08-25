"use client";

import React, { useEffect, useMemo } from "react";
import { Chess } from "chess.js";
import { Chessboard } from "react-chessboard";
import {
  ChessKnight,
  RefreshCw,
} from "lucide-react";
import { describeMove } from "@/utils/chessFunctions";


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


function sideName(color) {
  return color === "w" ? "white" : "black";
}


function toUci(move) {
  return `${move.from}${move.to}${move.promotion || ""}`;
}


function isPromotionMove(from, to) {
  return (
    (from[1] === "7" && to[1] === "8") ||
    (from[1] === "2" && to[1] === "1")
  );
}


/*
 * This is the whole frontend-owned chess handoff:
 *
 * 1. Ed's move has already been applied to `chess`.
 * 2. Create a revision-bound menu of legal Iris responses.
 * 3. For each legal response, precompute its successor FEN.
 *
 * Iris sees the compact legal-move projection.
 * The backend retains the full transition cabinet.
 */
function buildMusePreparation(chess, preparedForRevision, precedingMoveNarration) {
  const legalMoves = chess.moves({ verbose: true });

  const legalMoveDisplay = legalMoves.map((move) => ({
    move: toUci(move),
    san: move.san,
  }));

  const beforeFen = chess.fen();

  const transitions = legalMoves.map((move) => {
    const moveInput = {
      from: move.from,
      to: move.to,
      promotion: move.promotion,
    };

    // This is the canonical deterministic move packet.
    const moveEvent = describeMove(beforeFen, moveInput);

    // We still need a post-move Chess instance for its ASCII board rendering.
    const successor = new Chess(moveEvent.after_fen);

    return {
      move: toUci(move),

      next_state: {
        fen: moveEvent.after_fen,
      },

      after_ascii: successor.ascii(),

      // Convenient top-level fields for the current UI / prompt cut:
      san: moveEvent.san,
      narration: moveEvent.narration,

      // Full structured receipt for Iris, persistence, and future UI history:
      move_event: moveEvent,
    };
  });

  return {
    prepared_for_revision: preparedForRevision,
    prepared_for_actor: "muse",

    // Prompt-visible material for this immediate Iris turn.
    context: {
      preceding_move_narration: precedingMoveNarration,
      fen: chess.fen(),
      ascii: chess.ascii(),
      side_to_move: sideName(chess.turn()),
      legal_moves: legalMoveDisplay,
    },

    // Backend-only operational table: move -> successor state.
    transitions,
  };
}


function buildChessTurnAction({
  game,
  sourceSquare,
  targetSquare,
}) {
  const canonicalFen = game?.state?.fen;

  if (!canonicalFen) {
    return null;
  }

  const chess = new Chess(canonicalFen);

  const promotion = isPromotionMove(sourceSquare, targetSquare)
    ? "q"
    : undefined;

  let moved;

  try {
    moved = chess.move({
      from: sourceSquare,
      to: targetSquare,
      promotion,
    });
  } catch (error) {
    return null;
  }

  if (!moved) {
    return null;
  }

  const moveUci = toUci(moved);
  const nextFen = chess.fen();
  const nextRevision = (game.revision ?? 0) + 1;

  // `canonicalFen` is the pre-move position.
  // This independently replays and verifies the same legal move,
  // then gives us the canonical narration/fact receipt.
  const moveEvent = describeMove(
    canonicalFen,
    {
      from: moved.from,
      to: moved.to,
      promotion: moved.promotion,
    },
    nextFen,
  );

  return {
    action_type: "take_game_turn",

    action_data: {
      game_id: game.game_id,
      expected_revision: game.revision ?? 0,

      operation: {
        move: moveUci,
      },

      // Ed's post-move state, authored by chess.js.
      next_state: {
        fen: nextFen,
      },

      // Iris's legal, precomputed reply universe.
      // `chess` is already positioned after Ed's accepted move.
      prepare_muse_turn: buildMusePreparation(
        chess,
        nextRevision,
        moveEvent.narration,
      ),

      // Durable human-facing record of this accepted action.
      message_metadata: {
        action_type: "take_game_turn",
        game_id: game.game_id,
        game_type: "chess",
        turn_number: nextRevision,
        narration: moveEvent.narration,

        table: {
          // The side that just made this move.
          side: moved.color === "w" ? "white" : "black",
          board_ascii: chess.ascii(),
          fen: nextFen,
        },
      },
    },
  };
}


const ChessGamePanel = ({
  open,
  onClose,
  game,
  loading = false,
  error = null,
  onRefresh,
  turnActions = [],
  setTurnActions,
}) => {
  const gameId = game?.game_id || null;
  const revision = game?.revision ?? null;

  const canonicalFen =
    game?.state?.fen ||
    game?.context?.fen ||
    null;

  const draftAction = useMemo(() => {
    return turnActions.find((action) => (
      action.action_type === "take_game_turn" &&
      action.action_data?.game_id === gameId &&
      action.action_data?.expected_revision === revision
    )) || null;
  }, [turnActions, gameId, revision]);

  /*
   * A chess draft belongs to exactly one game revision.
   *
   * If a reload or websocket update advances the game, remove old chess
   * drafts while leaving future non-game composer actions alone.
   */
  useEffect(() => {
    if (!gameId || revision === null || !setTurnActions) {
      return;
    }

    setTurnActions((previous) => previous.filter((action) => {
      if (action.action_type !== "take_game_turn") {
        return true;
      }

      return (
        action.action_data?.game_id === gameId &&
        action.action_data?.expected_revision === revision
      );
    }));
  }, [gameId, revision, setTurnActions]);

  // While drafted, show Ed the position his move would create.
  // Remove the tile and this immediately becomes canonicalFen again.
  const displayedFen =
    draftAction?.action_data?.next_state?.fen ||
    canonicalFen;

  const musePlan =
    game?.state?.muse_plan ??
    game?.context?.muse_plan ??
    null;

  const turnLabel = getTurnLabel(canonicalFen);

  const lastMove =
    game?.last_turn?.result?.notation ||
    game?.last_turn?.result?.move ||
    null;

  // V1 assumption: Ed is White, Iris is Black.
  const isEdTurn =
    canonicalFen?.split(/\s+/)[1] === "w";

  const canDraftMove =
    Boolean(gameId) &&
    Boolean(canonicalFen) &&
    game?.status === "active" &&
    isEdTurn;

  const handlePieceDrop = ({
    sourceSquare,
    targetSquare,
  }) => {
    if (!targetSquare || !canDraftMove || !setTurnActions) {
      return false;
    }

    const nextAction = buildChessTurnAction({
      game,
      sourceSquare,
      targetSquare,
    });

    if (!nextAction) {
      return false;
    }

    setTurnActions((previous) => [
      ...previous.filter((action) => !(
        action.action_type === "take_game_turn" &&
        action.action_data?.game_id === gameId
      )),
      nextAction,
    ]);

    return true;
  };

  const chessboardOptions = {
    id: `game-${gameId || "board"}`,
    position: displayedFen,
    allowDragging: canDraftMove,
    dragActivationDistance: 1,

    canDragPiece: ({ square }) => {
      if (!canDraftMove || !square || !canonicalFen) {
        return false;
      }

      const chess = new Chess(canonicalFen);
      const piece = chess.get(square);

      return piece?.color === "w";
    },

    onPieceDrop: handlePieceDrop,

    boardStyle: {
      borderRadius: "10px",
      overflow: "hidden",
      border: "2px solid rgba(192, 132, 252, 0.45)",
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

  if (!open) return null;

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
        ) : !canonicalFen ? (
          <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4 text-sm text-neutral-400">
            This game has no renderable chess position.
          </div>
        ) : (
          <>
            <div className="mx-auto w-full max-w-[390px]">
              <Chessboard options={chessboardOptions} />
            </div>

            {draftAction && (
              <div className="mt-4 rounded-xl border border-purple-400/40 bg-purple-950/30 p-3 text-sm text-purple-100">
                <div className="font-semibold">
                  Drafted move: {draftAction.action_data.message_metadata?.narration}
                </div>

                <div className="mt-1 text-xs text-purple-200/70">
                  Still only a draft. Add your table talk, then press Send.
                </div>
              </div>
            )}

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

          </>
        )}
      </div>
    </aside>
  );
};


export default ChessGamePanel;