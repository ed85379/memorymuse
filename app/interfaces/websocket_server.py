from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from dataclasses import dataclass, field
from typing import Dict, Set, List
import json
from app.databases.memory_indexer import assign_message_id

router = APIRouter()


@dataclass
class ClientConnection:
    websocket: WebSocket
    modality: str
    channels: Set[str] = field(default_factory=set)

# Maintain separate connection pools by modality
active_connections: Dict[str, List[ClientConnection]] = {
    "frontend": [],
    "webui": [],
    "speaker": [],
    "discord": [],
}

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        init_msg = await websocket.receive_json()
        modality = init_msg.get("listen_as", "webui")
        print(f"New {modality} connection")

        client = ClientConnection(websocket=websocket, modality=modality)

        # Default subscriptions by modality
        if modality == "frontend":
            # global UI + chat by default
            client.channels.update({"muse-actions", "muse-chat", "muse-thread"})
        elif modality == "webui":
            # global UI + chat by default
            client.channels.update({"muse-actions", "muse-chat", "muse-thread"})
        elif modality == "speaker":
            client.channels.add("speaker")
        elif modality == "discord":
            client.channels.add("discord")

        active_connections.setdefault(modality, []).append(client)

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[{modality}] Non-JSON message: {raw}")
                continue

            action = msg.get("action")

            if modality == "webui" and action in ("subscribe", "unsubscribe"):
                new_channels = set(msg.get("channels", []))
                if action == "subscribe":
                    client.channels.update(new_channels)
                else:
                    client.channels.difference_update(new_channels)
                print(f"[webui] {action} {new_channels}, now: {client.channels}")
                continue

            # fallback echo
            print(f"[{modality}] Received from client: {raw}")
            await websocket.send_text(f"Muse ({modality}): {raw}")

    except WebSocketDisconnect:
        for modality, connections in active_connections.items():
            for c in list(connections):
                if c.websocket is websocket:
                    connections.remove(c)
                    print(f"{modality} client disconnected")

# Broadcast to all clients listening under a given modality
async def broadcast_message(
    message: str,
    timestamp: str,
    role: str,
    *,
    to_modality: str = "webui",
    channels: Set[str] | None = None,
    project_id: str = "",
    thread_id: str = "",
    message_id: str = "",
    payload_type: str = "muse_message",
):
    if channels is None:
        channels = {"muse-chat"}  # default lane for plain messages

    msg_dict = {
        "timestamp": timestamp,
        "role": role,
        "source": "webui",
        "message": message,
    }

    if not message_id:
        message_id = assign_message_id(msg_dict)


    connections = active_connections.get(to_modality, [])
    print(f"Broadcasting {payload_type} to {to_modality} on {channels} ({len(connections)} clients)")

    for client in list(connections):
        try:
            if client.channels.intersection(channels):
                await client.websocket.send_text(json.dumps({
                    "type": payload_type,
                    "message": message,
                    "role": role,
                    "message_id": message_id,
                    "project_id": project_id,
                    "thread_id": thread_id,
                    "channels": list(channels),
                    "timestamp": timestamp,
                }))
        except Exception:
            connections.remove(client)