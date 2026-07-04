import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "sqlite:///nub_system.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    return database_url


class BaseConfig:
    SECRET_KEY = os.getenv(
        "JWT_SECRET_KEY", "change-me-in-development-use-at-least-32-bytes"
    )
    JWT_SECRET_KEY = os.getenv(
        "JWT_SECRET_KEY", "change-me-in-development-use-at-least-32-bytes"
    )
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)
    SQLALCHEMY_DATABASE_URI = get_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
    BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")
    DEFAULT_CORS_ORIGINS = ",".join(
        [
            FRONTEND_URL,
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:4017",
            "http://127.0.0.1:4017",
        ]
    )
    SOCKET_CORS_ORIGINS = os.getenv("SOCKET_CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
    CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
    CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
    CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")
    CLOUDINARY_FOLDER_NAME = os.getenv("CLOUDINARY_FOLDER_NAME", "nub-system")
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class ProductionConfig(BaseConfig):
    DEBUG = False


def get_config():
    env = os.getenv("FLASK_ENV", "development").lower()
    if env == "production":
        return ProductionConfig
    return DevelopmentConfig
