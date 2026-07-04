from flask import Flask

from app.config import get_config
from app.extensions import cors, db, jwt, migrate, socketio
from app.modules import register_blueprints
from app.seeds import seed_initial_data
from app.socket_events import register_socket_events


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or get_config())

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"].split(",")}},
        supports_credentials=True,
    )
    socketio.init_app(
        app,
        cors_allowed_origins=app.config["SOCKET_CORS_ORIGINS"].split(","),
    )

    register_blueprints(app)
    register_socket_events(socketio)

    @app.cli.command("seed")
    def seed_command():
        seed_initial_data()
        print("Seed inicial creado.")

    return app
