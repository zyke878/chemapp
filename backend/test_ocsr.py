"""Run with:  pytest -v   (from the backend/ folder). Uses fake responses, no model needed."""
import io

import pytest
import requests
from PIL import Image

import ocsr


class FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("bad json")
        return self._payload


def png_bytes(size=(120, 90), mode="RGB", color=(0, 0, 0), fmt="PNG"):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format=fmt)
    return buf.getvalue()


def patch_http(monkeypatch, responder):
    calls = []

    def fake(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return responder(method, path, kwargs)

    monkeypatch.setattr(ocsr, "_http", fake)
    return calls


# ---------- image preparation ----------
def test_valid_image_becomes_rgb_png():
    out = Image.open(io.BytesIO(ocsr.prepare_image(png_bytes(mode="RGBA", color=(0, 0, 0, 255)))))
    assert out.mode == "RGB" and out.format == "PNG"


def test_transparent_background_becomes_white():
    out = Image.open(io.BytesIO(ocsr.prepare_image(png_bytes(mode="RGBA", color=(0, 0, 0, 0)))))
    assert out.getpixel((5, 5)) == (255, 255, 255)


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "BMP", "GIF", "TIFF"])
def test_common_screenshot_formats_are_accepted(fmt):
    out = Image.open(io.BytesIO(ocsr.prepare_image(png_bytes(fmt=fmt))))
    assert out.format == "PNG" and out.mode == "RGB"


def test_large_image_is_scaled_down():
    out = Image.open(io.BytesIO(ocsr.prepare_image(png_bytes(size=(4000, 3000)))))
    assert max(out.size) <= ocsr.MAX_SIDE


@pytest.mark.parametrize("bad", [b"", b"not an image", b"%PDF-1.4 fake"])
def test_non_images_rejected(bad):
    with pytest.raises(ocsr.InvalidImage):
        ocsr.prepare_image(bad)


def test_tiny_image_rejected():
    with pytest.raises(ocsr.InvalidImage):
        ocsr.prepare_image(png_bytes(size=(8, 8)))


# ---------- calling the service ----------
def test_success(monkeypatch):
    calls = patch_http(monkeypatch, lambda m, p, k: FakeResponse(200, {"smiles": "CCO", "confidence": "0.93"}))
    assert ocsr.image_to_smiles(png_bytes()) == {"smiles": "CCO", "confidence": 0.93}
    method, path, kwargs = calls[0]
    assert method == "POST" and path == "/predict" and "image" in kwargs["files"]


def test_missing_confidence_is_none(monkeypatch):
    patch_http(monkeypatch, lambda m, p, k: FakeResponse(200, {"smiles": "CCO"}))
    assert ocsr.image_to_smiles(png_bytes())["confidence"] is None


def test_empty_smiles_is_failure(monkeypatch):
    patch_http(monkeypatch, lambda m, p, k: FakeResponse(200, {"smiles": "  ", "confidence": 0.1}))
    with pytest.raises(ocsr.OcsrFailed):
        ocsr.image_to_smiles(png_bytes())


def test_service_422_is_failure(monkeypatch):
    patch_http(monkeypatch, lambda m, p, k: FakeResponse(422, {"code": "NO_STRUCTURE"}))
    with pytest.raises(ocsr.OcsrFailed):
        ocsr.image_to_smiles(png_bytes())


def test_service_500_is_failure(monkeypatch):
    patch_http(monkeypatch, lambda m, p, k: FakeResponse(500))
    with pytest.raises(ocsr.OcsrFailed):
        ocsr.image_to_smiles(png_bytes())


def test_service_503_is_unavailable(monkeypatch):
    patch_http(monkeypatch, lambda m, p, k: FakeResponse(503))
    with pytest.raises(ocsr.OcsrUnavailable):
        ocsr.image_to_smiles(png_bytes())


@pytest.mark.parametrize("exc", [requests.ConnectionError("refused"), requests.Timeout("slow")])
def test_connection_problems_are_unavailable(monkeypatch, exc):
    def responder(m, p, k):
        raise exc
    patch_http(monkeypatch, responder)
    with pytest.raises(ocsr.OcsrUnavailable):
        ocsr.image_to_smiles(png_bytes())


def test_bad_json_is_failure(monkeypatch):
    patch_http(monkeypatch, lambda m, p, k: FakeResponse(200, bad_json=True))
    with pytest.raises(ocsr.OcsrFailed):
        ocsr.image_to_smiles(png_bytes())


def test_invalid_image_never_calls_service(monkeypatch):
    calls = patch_http(monkeypatch, lambda m, p, k: FakeResponse(200, {"smiles": "CCO"}))
    with pytest.raises(ocsr.InvalidImage):
        ocsr.image_to_smiles(b"junk")
    assert calls == []


# ---------- availability ----------
def test_available_when_model_loaded(monkeypatch):
    patch_http(monkeypatch, lambda m, p, k: FakeResponse(200, {"status": "ok", "model_loaded": True}))
    assert ocsr.is_available() is True


def test_not_available_when_model_not_loaded(monkeypatch):
    patch_http(monkeypatch, lambda m, p, k: FakeResponse(200, {"status": "ok", "model_loaded": False}))
    assert ocsr.is_available() is False


def test_not_available_when_service_down(monkeypatch):
    def responder(m, p, k):
        raise requests.ConnectionError("refused")
    patch_http(monkeypatch, responder)
    assert ocsr.is_available() is False
