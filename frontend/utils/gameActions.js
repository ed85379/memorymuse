// frontend/utils/gameActions.js

const API_BASE = "/api/games";


async function readJsonResponse(response) {
  let data = null;

  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const detail =
      data?.detail ||
      data?.message ||
      `Game request failed with HTTP ${response.status}.`;

    throw new Error(detail);
  }

  return data;
}


export async function listGames({
  status = "all",
  gameType = null,
  limit = 200,
} = {}) {
  const params = new URLSearchParams();

  params.set("status", status);
  params.set("limit", String(limit));

  if (gameType) {
    params.set("game_type", gameType);
  }

  const response = await fetch(
    `${API_BASE}/?${params.toString()}`
  );

  const data = await readJsonResponse(response);
  return data.games || [];
}


export async function listGameTypes() {
  const response = await fetch(`${API_BASE}/types`);
  const data = await readJsonResponse(response);

  return data.game_types || [];
}


export async function getGameContext(gameId) {
  const response = await fetch(
    `${API_BASE}/${encodeURIComponent(gameId)}`
  );

  const data = await readJsonResponse(response);
  return data.game;
}


export async function createGame({
  gameId,
  gameType,
  label = null,
  createData = null,
}) {
  const response = await fetch(`${API_BASE}/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      game_id: gameId,
      game_type: gameType,
      label,
      create_data: createData,
    }),
  });

  const data = await readJsonResponse(response);
  return data.game;
}


export async function updateGame(gameId, patch) {
  const response = await fetch(
    `${API_BASE}/${encodeURIComponent(gameId)}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(patch),
    }
  );

  const data = await readJsonResponse(response);
  return data.game;
}


export function upsertGameInState(setGames, game) {
  if (!setGames || !game?.game_id) return;

  setGames((previous) => {
    const index = previous.findIndex(
      (item) => item.game_id === game.game_id
    );

    if (index === -1) {
      return [game, ...previous];
    }

    const next = [...previous];

    next[index] = {
      ...next[index],
      ...game,
    };

    return next;
  });
}


export function removeGameFromState(setGames, gameId) {
  if (!setGames) return;

  setGames((previous) =>
    previous.filter((game) => game.game_id !== gameId)
  );
}