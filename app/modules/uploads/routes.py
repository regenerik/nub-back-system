import os

from dotenv import find_dotenv, load_dotenv
from flask import Blueprint, current_app, request
import cloudinary
import cloudinary.uploader

from app.constants import Role
from app.security import roles_required

uploads_bp = Blueprint("uploads", __name__)

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


def cloudinary_config_value(key: str):
    load_dotenv(find_dotenv(usecwd=True), override=False)
    value = current_app.config.get(key) or os.getenv(key)
    if value:
        current_app.config[key] = value
    return value


@uploads_bp.post("/image")
@roles_required([Role.ADMIN, Role.RECEPCION, Role.CLIENTE])
def upload_image():
    image = request.files.get("image")
    if image is None:
        return {"message": "Tenes que enviar un archivo en el campo image."}, 400

    if image.mimetype not in ALLOWED_MIME_TYPES:
        return {"message": "Formato no permitido. Usar JPG, PNG o WEBP."}, 400
    if not all(
        [
            cloudinary_config_value("CLOUDINARY_CLOUD_NAME"),
            cloudinary_config_value("CLOUDINARY_API_KEY"),
            cloudinary_config_value("CLOUDINARY_API_SECRET"),
        ]
    ):
        return {
            "message": "Faltan variables de Cloudinary: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY y CLOUDINARY_API_SECRET.",
        }, 503

    cloudinary.config(
        cloud_name=cloudinary_config_value("CLOUDINARY_CLOUD_NAME"),
        api_key=cloudinary_config_value("CLOUDINARY_API_KEY"),
        api_secret=cloudinary_config_value("CLOUDINARY_API_SECRET"),
        secure=True,
    )

    result = cloudinary.uploader.upload(
        image,
        folder=cloudinary_config_value("CLOUDINARY_FOLDER_NAME") or "nub-system",
        resource_type="image",
        overwrite=False,
        unique_filename=True,
    )
    return {
        "secure_url": result["secure_url"],
        "public_id": result.get("public_id"),
        "folder": cloudinary_config_value("CLOUDINARY_FOLDER_NAME") or "nub-system",
    }
