from pathlib import Path

from app import image_delivery
from PIL import Image
from starlette.requests import Request


def request(etag=""):
    return Request({"type": "http", "headers": [(b"if-none-match", etag.encode())]})


def test_preview_preserves_geometry_and_original_and_revalidates(tmp_path, monkeypatch):
    monkeypatch.setattr(image_delivery.config, "UPLOADS_DIR", tmp_path)
    path = tmp_path / "frame.png"
    Image.new("RGB", (1217, 808), "red").save(path)
    original = path.read_bytes()
    response = image_delivery.image_response(path, request(), preview=True)
    assert Path(response.path).suffix == ".webp"
    assert Image.open(response.path).size == (1217, 808)
    assert path.read_bytes() == original
    assert response.headers["cache-control"] == "private, no-cache"
    assert (
        image_delivery.image_response(
            path, request(response.headers["etag"]), preview=True
        ).status_code
        == 304
    )
    Image.new("RGB", (1217, 808), "blue").save(path)
    assert (
        image_delivery.image_response(
            path, request(response.headers["etag"]), preview=True
        ).status_code
        == 200
    )


def test_original_is_available_and_has_distinct_etag(tmp_path, monkeypatch):
    monkeypatch.setattr(image_delivery.config, "UPLOADS_DIR", tmp_path)
    path = tmp_path / "frame.png"
    Image.new("RGB", (20, 20)).save(path)
    original = image_delivery.image_response(path, request())
    preview = image_delivery.image_response(path, request(), preview=True)
    assert Path(original.path) == path
    assert original.headers["etag"] != preview.headers["etag"]


def test_phone_orientation_is_preserved_in_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(image_delivery.config, "UPLOADS_DIR", tmp_path)
    path = tmp_path / "phone.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (40, 20), "red").save(path, exif=exif)
    response = image_delivery.image_response(path, request(), preview=True)
    with Image.open(response.path) as preview:
        assert preview.size == (40, 20)
        assert preview.getexif()[274] == 6
