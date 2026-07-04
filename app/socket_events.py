from flask import request
from flask_jwt_extended import decode_token
from flask_socketio import emit, join_room

from app.extensions import db
from app.modules.auth.models import User
from app.modules.barbers.models import Barber
from app.modules.clients.models import Client


ALLOWED_ROOM_PREFIXES = (
    "role:admin",
    "role:recepcion",
    "barber:",
    "branch:",
    "client:",
)


def _join_authenticated_rooms(auth):
    token = (auth or {}).get("token")
    if not token:
        return None
    decoded = decode_token(token)
    user_id = int(decoded["sub"])
    user = db.session.get(User, user_id)
    if not user or not user.is_active:
        return None

    rooms = [f"role:{user.role}"]
    barber = db.session.scalar(db.select(Barber).where(Barber.user_id == user.id))
    if barber:
        rooms.append(f"barber:{barber.id}")
    client_query = db.select(Client).where(Client.email == user.email)
    if user.google_account_id:
        client_query = db.select(Client).where(
            (Client.email == user.email) | (Client.google_account_id == user.google_account_id)
        )
    client = db.session.scalar(client_query)
    if client:
        rooms.append(f"client:{client.id}")
    for room in rooms:
        join_room(room)
    return {"user_id": user.id, "role": user.role, "rooms": rooms}


def register_socket_events(socketio):
    @socketio.on("connect")
    def handle_connect(auth=None):
        identity = _join_authenticated_rooms(auth)
        emit(
            "connection:ready",
            {
                "status": "connected",
                "sid": request.sid,
                "identity": identity,
                "message": "Socket.IO listo para notificaciones live.",
            },
        )

    @socketio.on("room:join")
    def handle_room_join(payload):
        room = (payload or {}).get("room")
        if not room or not room.startswith(ALLOWED_ROOM_PREFIXES):
            emit("room:error", {"message": "Sala no permitida."})
            return

        join_room(room)
        emit("room:joined", {"room": room})
