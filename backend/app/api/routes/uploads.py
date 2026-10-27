"""Upload e download delle immagini per l'input multimodale."""
import base64
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import verify_api_key
from app.api.schemas import (
    ImageUploadResponse,
)
from app.core import config, image_utils

router = APIRouter(tags=["uploads"])


# Gestione upload file multimodali

if os.path.exists("/data") and os.access("/data", os.W_OK):
    UPLOAD_DIR = Path("/data/uploads")
else:
    UPLOAD_DIR = config.BACKEND_DIR / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@router.post("/v1/upload", response_model=ImageUploadResponse, dependencies=[Depends(verify_api_key)])
async def upload_file_endpoint(file: UploadFile = File(...)):
    """Carica un'immagine per utilizzo multimodale, salvandola localmente e restituendo URL e base64 data_url."""
    filename = file.filename or "image.jpg"
    content_type = file.content_type or ""

    if not image_utils.is_supported_image(filename=filename, content_type=content_type):
        raise HTTPException(status_code=400, detail="Solo file di tipo immagine sono supportati.")

    contents = await file.read()
    if len(contents) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Dimensione massima file superata (limite 25MB).")

    # Ottimizza, orienta EXIF, ridimensiona a max 2048px e transcodifica HEIC/HEIF a JPEG
    try:
        opt_bytes, mime, w, h = image_utils.optimize_image_bytes(
            contents,
            max_dimension=2048,
            quality=85,
            force_jpeg=image_utils.is_heic_or_heif(filename=filename, content_type=content_type, raw_bytes=contents),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Impossibile elaborare l'immagine caricata: {e}") from e

    ext = ".jpg" if mime == "image/jpeg" else (Path(filename).suffix or ".jpg")
    safe_name = f"{uuid.uuid4().hex}{ext}"
    file_path = UPLOAD_DIR / safe_name

    with open(file_path, "wb") as f:
        f.write(opt_bytes)

    encoded_b64 = base64.b64encode(opt_bytes).decode("utf-8")
    data_url = f"data:{mime};base64,{encoded_b64}"

    return ImageUploadResponse(
        url=f"/v1/uploads/{safe_name}",
        data_url=data_url,
        filename=safe_name,
        width=w,
        height=h,
    )

@router.get("/v1/uploads/{filename}")
async def get_uploaded_file(filename: str):
    """Restituisce un file immagine caricato con intestazioni di sicurezza."""
    safe_filename = Path(filename).name
    file_path = UPLOAD_DIR / safe_filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File non trovato.")

    return FileResponse(
        str(file_path),
        headers={"X-Content-Type-Options": "nosniff"}
    )
