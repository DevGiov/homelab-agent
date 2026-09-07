"""
Image optimization and conversion utilities for multimodal vision models.
Handles HEIC/HEIF decoding, EXIF orientation normalization, resolution downscaling,
and JPEG transcoding to ensure compatibility with llama.cpp mmproj and web browsers.
"""

import base64
import io
import logging
from typing import Optional, Tuple

logger = logging.getLogger("image_utils")

# Register pillow_heif if available
_HEIF_ENABLED = False
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    _HEIF_ENABLED = True
    logger.info("pillow_heif successfully registered for HEIC/HEIF decoding.")
except Exception as e:
    logger.warning(f"pillow_heif not available or registration failed: {e}")

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None
    logger.error("PIL (Pillow) is not installed in the current environment.")


def is_heic_or_heif(filename: str = "", content_type: str = "", raw_bytes: bytes = b"") -> bool:
    """Rileva se un file o buffer è in formato HEIC / HEIF."""
    if filename:
        ext = filename.lower().split(".")[-1]
        if ext in ("heic", "heif", "heifs", "hif"):
            return True
    if content_type:
        ct = content_type.lower()
        if "heic" in ct or "heif" in ct:
            return True
    if raw_bytes and len(raw_bytes) >= 12:
        # Check ISO BMFF ftyp box
        # Bytes 4-8 are 'ftyp'
        if raw_bytes[4:8] == b"ftyp":
            major_brand = raw_bytes[8:12].lower()
            if major_brand in (b"heic", b"heix", b"heim", b"heis", b"mif1", b"msf1"):
                return True
            # Compatible brands in the rest of ftyp box
            box_size = int.from_bytes(raw_bytes[0:4], "big")
            compatible_brands = raw_bytes[16:min(box_size, 64)].lower()
            if b"heic" in compatible_brands or b"mif1" in compatible_brands:
                return True
    return False


def is_supported_image(filename: str = "", content_type: str = "", raw_bytes: bytes = b"") -> bool:
    """Verifica se il file è un'immagine supportata (incluso HEIC/HEIF)."""
    if content_type and content_type.startswith("image/"):
        return True
    if filename:
        ext = filename.lower().split(".")[-1]
        if ext in ("jpg", "jpeg", "png", "webp", "gif", "bmp", "heic", "heif", "heifs", "hif", "tiff", "tif"):
            return True
    if is_heic_or_heif(filename, content_type, raw_bytes):
        return True
    return False


def optimize_image_bytes(
    raw_bytes: bytes,
    max_dimension: int = 1920,
    quality: int = 85,
    force_jpeg: bool = False,
) -> Tuple[bytes, str, int, int]:
    """
    Decodifica i byte dell'immagine (incluso HEIC/HEIF), applica la rotazione EXIF nativa,
    ridimensiona proporzionalmente se supera max_dimension e salva come JPEG ottimizzato.
    
    Ritorna: (bytes_ottimizzati, mime_type, width, height)
    """
    if not Image:
        return raw_bytes, "application/octet-stream", 0, 0

    bio = io.BytesIO(raw_bytes)
    img = Image.open(bio)

    # 1. Normalizza orientamento EXIF (molto comune nelle foto iPhone scattate in verticale)
    if ImageOps:
        try:
            img = ImageOps.exif_transpose(img)
        except Exception as e:
            logger.debug(f"exif_transpose failed: {e}")

    orig_w, orig_h = img.size

    # 2. Downscale proporzionale se supera la dimensione massima
    if orig_w > max_dimension or orig_h > max_dimension:
        img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

    final_w, final_h = img.size

    # 3. Determina formato di output
    # Se il formato originale è HEIC/HEIF o force_jpeg è True, convertiamo in JPEG
    is_source_heif = getattr(img, "format", "") in ("HEIF", "HEIC") or is_heic_or_heif(raw_bytes=raw_bytes)
    
    if force_jpeg or is_source_heif or img.format in ("JPEG", "MPO") or img.format is None:
        # Gestione trasparenza per JPEG (sfondo bianco)
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            alpha_mask = img.split()[-1] if len(img.split()) > 3 else None
            bg.paste(img, mask=alpha_mask)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        out_buf = io.BytesIO()
        img.save(out_buf, format="JPEG", quality=quality, optimize=True)
        return out_buf.getvalue(), "image/jpeg", final_w, final_h
    elif img.format == "PNG":
        out_buf = io.BytesIO()
        img.save(out_buf, format="PNG", optimize=True)
        return out_buf.getvalue(), "image/png", final_w, final_h
    elif img.format == "WEBP":
        out_buf = io.BytesIO()
        img.save(out_buf, format="WEBP", quality=quality)
        return out_buf.getvalue(), "image/webp", final_w, final_h
    else:
        # Fallback sicuro a JPEG per qualsiasi altro formato esotico
        if img.mode != "RGB":
            img = img.convert("RGB")
        out_buf = io.BytesIO()
        img.save(out_buf, format="JPEG", quality=quality, optimize=True)
        return out_buf.getvalue(), "image/jpeg", final_w, final_h


def normalize_image_data_url(data_url: str, max_dimension: int = 1920) -> str:
    """
    Intercetta una stringa data URL (es. 'data:image/heic;base64,...' o 'data:image/jpeg;base64,...').
    Se è HEIC/HEIF o supera 1.5MB di payload, la transcodifica e ridimensiona a JPEG standard.
    Ritorna la stringa data:image/jpeg;base64,... normalizzata.
    Se è un URL web standard (es. /v1/uploads/...), lo lascia invariato.
    """
    if not data_url or not isinstance(data_url, str):
        return data_url

    if not data_url.startswith("data:"):
        return data_url

    try:
        parts = data_url.split(",", 1)
        if len(parts) != 2:
            return data_url
        header, b64_payload = parts

        header_lower = header.lower()
        is_heic = "heic" in header_lower or "heif" in header_lower
        is_generic_or_empty = header_lower in ("data:;base64", "data:application/octet-stream;base64")
        # Se payload base64 supera ~1.5MB o è HEIC
        needs_optimization = is_heic or is_generic_or_empty or len(b64_payload) > 1_500_000

        if not needs_optimization:
            # È già un'immagine standard leggera (JPEG/PNG/WebP)
            return data_url

        raw_bytes = base64.b64decode(b64_payload)
        opt_bytes, mime, w, h = optimize_image_bytes(
            raw_bytes,
            max_dimension=max_dimension,
            quality=85,
            force_jpeg=True,
        )
        new_b64 = base64.b64encode(opt_bytes).decode("utf-8")
        logger.info(f"Normalizzata immagine {w}x{h} ({len(raw_bytes)} bytes -> {len(opt_bytes)} bytes) a JPEG")
        return f"data:{mime};base64,{new_b64}"
    except Exception as e:
        logger.warning(f"Errore durante normalizzazione data URL immagine: {e}")
        return data_url
