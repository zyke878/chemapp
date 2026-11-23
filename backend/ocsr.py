"""Image-to-SMILES client (Phase 5).

MolScribe needs an old stack (torch < 2.0, OpenNMT-py 2.2, Python <= 3.10 on
Windows), so it runs as a separate small service (see ../ocr_service). This
module prepares the image, sends it to that service and returns the result.

    image_to_smiles(image_bytes) -> {"smiles": str, "confidence": float | None}
Raises:
    InvalidImage     the upload is not a usable image
    OcsrUnavailable  the OCR service is not running / not ready / timed out
    OcsrFailed       the service ran but found no structure

Live check (service must be running):  python ocsr.py path/to/structure.png
"""
import io
import os

import requests
from PIL import Image

OCR_SERVICE_URL = os.getenv("OCR_SERVICE_URL", "http://127.0.0.1:8001").rstrip("/")
OCR_TIMEOUT = float(os.getenv("OCR_TIMEOUT", "120"))   # first CPU prediction can be slow
HEALTH_TIMEOUT = 1.5

# Below this confidence the API adds a "please check the structure" warning.
# This is a starting guess. Tune it after testing real images.
LOW_CONFIDENCE = 0.75

MAX_SIDE = 2000      # larger images are scaled down (the model works at ~384 px anyway)
MIN_SIDE = 16
Image.MAX_IMAGE_PIXELS = 50_000_000


class InvalidImage(ValueError):
    """The uploaded file cannot be used as an image."""


class OcsrUnavailable(Exception):
    """The OCR service cannot be reached or is not ready."""


class OcsrFailed(Exception):
    """The OCR service ran but could not read a structure."""


def _http(method, path, **kwargs):
    """One HTTP call to the OCR service. Tests replace this function."""
    return requests.request(method, OCR_SERVICE_URL + path, **kwargs)


def is_available():
    """True if the OCR service is up and its model is loaded."""
    try:
        resp = _http("GET", "/health", timeout=HEALTH_TIMEOUT)
        return resp.status_code == 200 and bool(resp.json().get("model_loaded"))
    except (requests.RequestException, ValueError):
        return False


def prepare_image(image_bytes):
    """Validate an upload and return clean PNG bytes (RGB, white background)."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception as e:
        raise InvalidImage("The file is not a readable image (use PNG, JPG or similar).") from e

    if min(img.size) < MIN_SIDE:
        raise InvalidImage("The image is too small to contain a structure.")

    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    if has_alpha:
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[3])   # transparent areas become white, not black
        img = background
    else:
        img = img.convert("RGB")

    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def image_to_smiles(image_bytes):
    png = prepare_image(image_bytes)
    try:
        resp = _http("POST", "/predict", files={"image": ("structure.png", png, "image/png")},
                     timeout=OCR_TIMEOUT)
    except requests.RequestException as e:
        raise OcsrUnavailable(f"OCR service not reachable: {e}") from e

    if resp.status_code == 503:
        raise OcsrUnavailable("OCR service is running but its model is not loaded.")
    if resp.status_code == 422:
        raise OcsrFailed("No structure recognised.")
    if resp.status_code != 200:
        raise OcsrFailed(f"OCR service error (HTTP {resp.status_code}).")

    try:
        data = resp.json()
    except ValueError as e:
        raise OcsrFailed("OCR service returned invalid JSON.") from e
    smiles = (data.get("smiles") or "").strip()
    if not smiles:
        raise OcsrFailed("No structure recognised.")
    confidence = data.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    return {"smiles": smiles, "confidence": confidence}


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) != 2:
        sys.exit("Usage: python ocsr.py path/to/structure.png")
    with open(sys.argv[1], "rb") as f:
        raw = f.read()
    try:
        print(json.dumps(image_to_smiles(raw), indent=2))
    except (InvalidImage, OcsrUnavailable, OcsrFailed) as e:
        sys.exit(f"{type(e).__name__}: {e}")
