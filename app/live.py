from app.extensions import socketio


def emit_live_event(event_name: str, payload: dict, room: str | None = None) -> None:
    socketio.emit(event_name, payload, room=room, namespace="/")


def appointment_room(branch_id: int | None = None, barber_id: int | None = None) -> list[str]:
    rooms = ["role:admin", "role:recepcion"]
    if branch_id is not None:
        rooms.append(f"branch:{branch_id}")
    if barber_id is not None:
        rooms.append(f"barber:{barber_id}")
    return rooms
