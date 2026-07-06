import eventlet

eventlet.monkey_patch()

from app import create_app
from app.extensions import socketio
import os

app = create_app()

if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=app.config["DEBUG"],
        use_reloader=False,
    )
