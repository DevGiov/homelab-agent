"""Ridimensionamento dei data URL prima dell'invio. Nessuna GPU e nessuna rete."""
import base64
import io

from PIL import Image

from app.core.image_utils import normalize_image_data_url


def _data_url(width: int, height: int, fmt: str) -> str:
    image = Image.new("RGB", (width, height), (20, 40, 60))
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    payload = base64.b64encode(buf.getvalue()).decode("ascii")
    mime = "image/jpeg" if fmt == "JPEG" else "image/webp"
    return f"data:{mime};base64,{payload}"


def _open(data_url: str) -> Image.Image:
    payload = data_url.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(payload)))


def test_a_short_jpeg_over_the_side_limit_is_downscaled():
    # Un colore pieno resta molto sotto 1,5 MB di base64: prima questo caso non veniva toccato
    url = _data_url(2400, 1800, "JPEG")
    assert len(url.split(",", 1)[1]) < 1_500_000

    out = normalize_image_data_url(url)

    assert out.startswith("data:image/jpeg;base64,")
    assert max(_open(out).size) <= 1920


def test_an_image_already_within_the_side_limit_is_not_enlarged():
    url = _data_url(320, 200, "JPEG")

    out = normalize_image_data_url(url)

    assert _open(out).size == (320, 200)


def test_webp_becomes_jpeg_and_is_downscaled():
    url = _data_url(3000, 100, "WEBP")

    out = normalize_image_data_url(url)

    assert out.startswith("data:image/jpeg;base64,")
    assert max(_open(out).size) <= 1920


def test_a_non_data_url_is_left_unchanged():
    assert normalize_image_data_url("/tmp/foto.jpg") == "/tmp/foto.jpg"
