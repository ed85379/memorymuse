"use client";

import React from "react";
import { nanoid } from "nanoid";
import {
  Archive,
  ArchiveRestore,
  ArrowUpDown,
  ChessKnight,
  Dices,
  LoaderCircle,
  Pencil,
  Plus,
} from "lucide-react";

import {
  createGame,
  listGameTypes,
  removeGameFromState,
  updateGame,
  upsertGameInState,
} from "@/utils/gameActions";



function getGameIcon(gameType) {
  if (gameType === "chess") {
    return ChessKnight;
  }

  return Dices;
}


function formatGameDate(value) {
  if (!value) return "";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return date.toLocaleString();
}


function getLastMoveLabel(game) {
  return (
    game?.last_turn?.result?.notation ||
    game?.last_turn?.result?.move ||
    game?.last_turn?.operation?.move ||
    null
  );
}


export default function GameManagerPanel({
  games,
  setGames,
  fetchGames,
  setGameManagerOpen,
  openGameId,
  onOpenGame,
  onClearOpenGame,
}) {
  const [gameTypes, setGameTypes] = React.useState([
    {
      game_type: "chess",
      label: "Chess",
    },
  ]);

  const [sortField, setSortField] = React.useState("label");
  const [sortDir, setSortDir] = React.useState("asc");
  const [showArchived, setShowArchived] = React.useState(false);

  const [createPanelOpen, setCreatePanelOpen] =
    React.useState(false);

  const [newGameType, setNewGameType] =
    React.useState("chess");

  const [newGameLabel, setNewGameLabel] =
    React.useState("");

  const [editingGameId, setEditingGameId] =
    React.useState(null);

  const [editingLabel, setEditingLabel] =
    React.useState("");

  const [creating, setCreating] = React.useState(false);
  const [busyGameId, setBusyGameId] = React.useState(null);
  const [error, setError] = React.useState("");


  React.useEffect(() => {
    let cancelled = false;

    listGameTypes()
      .then((types) => {
        if (cancelled || !types.length) return;

        setGameTypes(types);

        if (
          !types.some(
            (definition) =>
              definition.game_type === newGameType
          )
        ) {
          setNewGameType(types[0].game_type);
        }
      })
      .catch((err) => {
        console.error("Failed to load game types:", err);
      });

    return () => {
      cancelled = true;
    };
  }, []);


  const sortedGames = React.useMemo(() => {
    const copy = [...(games || [])];

    copy.sort((a, b) => {
      let left;
      let right;

      if (sortField === "label") {
        left = (a.label || "").toLowerCase();
        right = (b.label || "").toLowerCase();
      } else {
        left = new Date(
          a.updated_at || a.created_at || 0
        ).getTime();

        right = new Date(
          b.updated_at || b.created_at || 0
        ).getTime();
      }

      if (left < right) {
        return sortDir === "asc" ? -1 : 1;
      }

      if (left > right) {
        return sortDir === "asc" ? 1 : -1;
      }

      return 0;
    });

    return copy;
  }, [games, sortField, sortDir]);


  const activeGames = sortedGames.filter(
    (game) => game.status !== "archived"
  );

  const archivedGames = sortedGames.filter(
    (game) => game.status === "archived"
  );


  const toggleSort = () => {
    if (sortField === "label") {
      setSortField("updated_at");
      setSortDir("desc");
      return;
    }

    setSortField("label");
    setSortDir("asc");
  };


  const handleCreateGame = async () => {
    if (creating) return;

    setCreating(true);
    setError("");

    const gameId = nanoid();
    const now = new Date().toISOString();

    const selectedDefinition =
      gameTypes.find(
        (definition) =>
          definition.game_type === newGameType
      ) || gameTypes[0];

    const label =
      newGameLabel.trim() ||
      selectedDefinition?.label ||
      "New Game";

    const optimisticGame = {
      game_id: gameId,
      game_type: newGameType,
      label,
      status: "active",
      revision: 0,
      last_turn: null,
      created_at: now,
      updated_at: now,
      optimistic: true,
    };

    upsertGameInState(setGames, optimisticGame);

    try {
      const createdGame = await createGame({
        gameId,
        gameType: newGameType,
        label,
        createData: null,
      });

      upsertGameInState(setGames, {
        ...createdGame,
        optimistic: false,
      });

      setNewGameLabel("");
      setCreatePanelOpen(false);

      onOpenGame(createdGame.game_id);
      setGameManagerOpen(false);
    } catch (err) {
      console.error("Failed to create game:", err);

      removeGameFromState(setGames, gameId);

      setError(
        err.message || "Failed to create the game."
      );
    } finally {
      setCreating(false);
    }
  };


  const commitLabel = async (game) => {
    const label = editingLabel.trim();

    setEditingGameId(null);
    setEditingLabel("");

    if (!label || label === game.label) {
      return;
    }

    setBusyGameId(game.game_id);
    setError("");

    try {
      const updatedGame = await updateGame(
        game.game_id,
        { label }
      );

      upsertGameInState(setGames, updatedGame);
    } catch (err) {
      console.error("Failed to rename game:", err);

      setError(
        err.message || "Failed to rename the game."
      );
    } finally {
      setBusyGameId(null);
    }
  };


  const setGameArchived = async (
    game,
    shouldArchive
  ) => {
    setBusyGameId(game.game_id);
    setError("");

    try {
      const updatedGame = await updateGame(
        game.game_id,
        {
          status: shouldArchive
            ? "archived"
            : "active",
        }
      );

      upsertGameInState(setGames, updatedGame);

      if (
        shouldArchive &&
        openGameId === game.game_id
      ) {
        onClearOpenGame();
      }
    } catch (err) {
      console.error(
        "Failed to change game status:",
        err
      );

      setError(
        err.message ||
          "Failed to change the game status."
      );
    } finally {
      setBusyGameId(null);
    }
  };


  const restoreAndOpen = async (game) => {
    setBusyGameId(game.game_id);
    setError("");

    try {
      const updatedGame = await updateGame(
        game.game_id,
        {
          status: "active",
        }
      );

      upsertGameInState(setGames, updatedGame);

      onOpenGame(game.game_id);
      setGameManagerOpen(false);
    } catch (err) {
      console.error(
        "Failed to restore game:",
        err
      );

      setError(
        err.message || "Failed to restore the game."
      );
    } finally {
      setBusyGameId(null);
    }
  };


  const renderGameRow = (
    game,
    { archived = false } = {}
  ) => {
    const GameIcon = getGameIcon(game.game_type);
    const lastMove = getLastMoveLabel(game);
    const isBusy = busyGameId === game.game_id;
    const isOpen = openGameId === game.game_id;

    return (
      <div
        key={game.game_id}
        className={`
          border-t border-neutral-800 px-3 py-2
          ${isOpen ? "bg-purple-950/25" : ""}
        `}
      >
        <div className="flex items-start gap-2">
          <GameIcon
            className="mt-0.5 h-4 w-4 shrink-0 text-purple-300"
          />

          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1">
              {editingGameId === game.game_id ? (
                <input
                  autoFocus
                  value={editingLabel}
                  onChange={(event) =>
                    setEditingLabel(event.target.value)
                  }
                  onBlur={() => commitLabel(game)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      commitLabel(game);
                    }

                    if (event.key === "Escape") {
                      setEditingGameId(null);
                      setEditingLabel("");
                    }
                  }}
                  className="
                    w-full rounded border border-neutral-700
                    bg-neutral-900/80 px-1.5 py-0.5
                    text-sm text-neutral-100
                    outline-none focus:ring-1
                    focus:ring-purple-500
                  "
                />
              ) : (
                <>
                  <div className="truncate text-sm font-medium text-neutral-100">
                    {game.label || "(untitled game)"}
                  </div>

                  <button
                    type="button"
                    onClick={() => {
                      setEditingGameId(game.game_id);
                      setEditingLabel(game.label || "");
                    }}
                    className="
                      shrink-0 rounded p-0.5
                      text-neutral-500
                      hover:bg-neutral-800
                      hover:text-purple-300
                    "
                    title="Edit game label"
                  >
                    <Pencil className="h-3 w-3" />
                  </button>
                </>
              )}
            </div>

            <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-neutral-500">
              <span>{game.game_type}</span>
              <span>Revision {game.revision ?? 0}</span>

              {lastMove && (
                <span>Last: {lastMove}</span>
              )}

              <span>
                {formatGameDate(
                  game.updated_at || game.created_at
                )}
              </span>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1">
            {isBusy ? (
              <LoaderCircle className="h-4 w-4 animate-spin text-purple-300" />
            ) : archived ? (
              <>
                <button
                  type="button"
                  onClick={() => restoreAndOpen(game)}
                  className="
                    rounded border border-purple-500/60
                    px-1.5 py-0.5 text-[11px]
                    text-purple-200
                    hover:bg-purple-500/10
                  "
                >
                  Open
                </button>

                <button
                  type="button"
                  onClick={() =>
                    setGameArchived(game, false)
                  }
                  className="
                    rounded p-1 text-neutral-400
                    hover:text-neutral-100
                  "
                  title="Restore game"
                >
                  <ArchiveRestore className="h-4 w-4" />
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => {
                    onOpenGame(game.game_id);
                    setGameManagerOpen(false);
                  }}
                  className="
                    rounded border border-purple-500/60
                    px-1.5 py-0.5 text-[11px]
                    text-purple-200
                    hover:bg-purple-500/10
                  "
                >
                  {isOpen ? "Table" : "Open"}
                </button>

                <button
                  type="button"
                  onClick={() =>
                    setGameArchived(game, true)
                  }
                  className="
                    rounded p-1 text-neutral-400
                    hover:text-neutral-100
                  "
                  title="Archive game"
                >
                  <Archive className="h-4 w-4" />
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    );
  };


  return (
    <div
      className="
        w-[420px] overflow-hidden rounded-xl
        border border-neutral-700
        bg-neutral-950 text-white
        shadow-2xl
      "
    >
      <div className="flex items-center justify-between border-b border-neutral-800 px-3 py-2">
        <div className="flex items-center gap-2">
          <ChessKnight className="h-4 w-4 text-purple-300" />
          <span className="text-sm font-semibold">
            Game Manager
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() =>
              setCreatePanelOpen((previous) => !previous)
            }
            className="
              inline-flex items-center gap-1 rounded
              border border-purple-500/60
              px-2 py-1 text-xs text-purple-200
              hover:bg-purple-500/10
            "
          >
            <Plus className="h-3 w-3" />
            Create
          </button>

          <button
            type="button"
            onClick={toggleSort}
            className="
              inline-flex items-center gap-1 rounded
              px-2 py-1 text-xs text-neutral-400
              hover:bg-neutral-800
              hover:text-neutral-100
            "
          >
            <ArrowUpDown className="h-3 w-3" />
            {sortField === "label" ? "Label" : "Updated"}
            {sortDir === "asc" ? " ↑" : " ↓"}
          </button>
        </div>
      </div>

      {createPanelOpen && (
        <div className="space-y-2 border-b border-neutral-800 bg-neutral-900/40 p-3">
          <select
            value={newGameType}
            onChange={(event) =>
              setNewGameType(event.target.value)
            }
            className="
              w-full rounded border border-neutral-700
              bg-neutral-900 px-2 py-1
              text-sm text-neutral-100
              outline-none focus:ring-1
              focus:ring-purple-500
            "
          >
            {gameTypes.map((definition) => (
              <option
                key={definition.game_type}
                value={definition.game_type}
              >
                {definition.label}
              </option>
            ))}
          </select>

          <input
            value={newGameLabel}
            onChange={(event) =>
              setNewGameLabel(event.target.value)
            }
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                handleCreateGame();
              }

              if (event.key === "Escape") {
                setCreatePanelOpen(false);
                setNewGameLabel("");
              }
            }}
            placeholder="Game label, optional"
            className="
              w-full rounded border border-neutral-700
              bg-neutral-900/80 px-2 py-1
              text-sm text-neutral-100
              outline-none focus:ring-1
              focus:ring-purple-500
            "
          />

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setCreatePanelOpen(false);
                setNewGameLabel("");
              }}
              className="
                rounded px-2 py-1 text-xs
                text-neutral-400
                hover:bg-neutral-800
                hover:text-neutral-100
              "
            >
              Cancel
            </button>

            <button
              type="button"
              disabled={creating}
              onClick={handleCreateGame}
              className="
                inline-flex items-center gap-1 rounded
                bg-purple-700 px-2 py-1
                text-xs text-white
                hover:bg-purple-600
                disabled:opacity-50
              "
            >
              {creating && (
                <LoaderCircle className="h-3 w-3 animate-spin" />
              )}

              Create Game
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="border-b border-red-900/50 bg-red-950/30 px-3 py-2 text-xs text-red-200">
          {error}
        </div>
      )}

      <div className="max-h-[60vh] overflow-y-auto">
        {activeGames.length === 0 ? (
          <div className="px-3 py-5 text-center text-sm text-neutral-500">
            No active games yet.
          </div>
        ) : (
          activeGames.map((game) =>
            renderGameRow(game)
          )
        )}

        <button
          type="button"
          onClick={() =>
            setShowArchived((previous) => !previous)
          }
          className="
            flex w-full items-center justify-between
            border-t border-neutral-800
            px-3 py-1.5 text-xs text-neutral-400
            hover:bg-neutral-900/60
            hover:text-neutral-100
          "
        >
          <span>Show archived</span>
          <span>{showArchived ? "▲" : "▼"}</span>
        </button>

        {showArchived && (
          <div>
            {archivedGames.length === 0 ? (
              <div className="px-3 py-4 text-center text-xs text-neutral-500">
                No archived games.
              </div>
            ) : (
              archivedGames.map((game) =>
                renderGameRow(game, {
                  archived: true,
                })
              )
            )}
          </div>
        )}
      </div>
    </div>
  );
}