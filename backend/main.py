"""Chemprop backend.

Run from the backend/ folder:
    uvicorn main:app --reload --port 8000
Interactive docs: http://localhost:8000/docs
"""
from collections import Counter
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import ocsr
import pubchem
from chem import analyze_smiles, split_largest_fragment, structure_svg, InvalidSmilesError
from explain import generate_explanations
from syllabus import SUPPORTED_BOARDS, SUPPORTED_GRADES, covers_everything, relevant_groups

app = FastAPI(title="Chemprop API", version="0.5.0")

# Origins your frontend runs on. Add yours if it differs.
#   5173 = Vite, 3000 = Next.js / Create React App,
#   5500 = VS Code Live Server (plain HTML)
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_SMILES_LENGTH = 500
MAX_NAME_LENGTH = 200
MAX_IMAGE_BYTES = 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# Errors: every error leaves the API as {"error": "...", "code": "..."}
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, extra: Optional[dict] = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.extra = extra or {}


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.message, "code": exc.code, **exc.extra},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "Missing or malformed request fields.", "code": "INVALID_REQUEST"},
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def config():
    """Boards and grades the app supports (use to fill the frontend dropdowns)."""
    return {"boards": SUPPORTED_BOARDS, "grades": SUPPORTED_GRADES, "image_input": ocsr.is_available()}


@app.post("/api/analyze")
def analyze(
    grade: int = Form(...),
    board: str = Form("CBSE"),
    smiles: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
):
    """Analyse a molecule. Send grade (10, 11 or 12) and exactly one of: smiles, name, image.

    board is optional and defaults to CBSE (the only supported board)."""
    # --- validate grade and board ---
    if grade not in SUPPORTED_GRADES:
        grades = ", ".join(str(g) for g in SUPPORTED_GRADES)
        raise ApiError(422, "INVALID_GRADE", f"Grade must be one of: {grades}.")
    board = (board or "").strip().upper() or "CBSE"     # the app only supports CBSE, so board is optional
    if board not in SUPPORTED_BOARDS:
        raise ApiError(422, "INVALID_BOARD", f"Supported boards: {', '.join(SUPPORTED_BOARDS)}.")

    # --- exactly one input ---
    smiles = smiles.strip() if smiles else None
    name = name.strip() if name else None
    has_image = image is not None and bool(image.filename)
    provided = [x for x in (bool(smiles), bool(name), has_image) if x]
    if len(provided) != 1:
        raise ApiError(422, "INVALID_INPUT", "Send exactly one of: smiles, name, image.")

    warnings = []
    pubchem_data = None
    source = "smiles"
    confidence = None

    # --- name: resolve to a SMILES through PubChem ---
    if name:
        if len(name) > MAX_NAME_LENGTH:
            raise ApiError(422, "INVALID_INPUT", "Name is too long.")
        try:
            pubchem_data = pubchem.lookup_by_name(name)
        except pubchem.PubChemUnavailable:
            raise ApiError(503, "PUBCHEM_UNAVAILABLE",
                           "Name lookup needs PubChem, which could not be reached. Try again, or enter a SMILES string.")
        if pubchem_data is None or not pubchem_data.get("smiles"):
            raise ApiError(404, "NAME_NOT_FOUND",
                           f"No compound found for '{name}'. Check the spelling, or enter a SMILES string.")
        smiles = pubchem_data["smiles"]
        source = "name"

    # --- image: read the structure with the OCR service ---
    if has_image:
        data = image.file.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise ApiError(413, "IMAGE_TOO_LARGE", "The image must be 10 MB or smaller.")
        try:
            ocr = ocsr.image_to_smiles(data)
        except ocsr.InvalidImage as e:
            raise ApiError(422, "INVALID_IMAGE", str(e))
        except ocsr.OcsrUnavailable:
            raise ApiError(503, "OCR_UNAVAILABLE",
                           "Image recognition is not available right now. Try typing the name or SMILES instead.")
        except ocsr.OcsrFailed:
            raise ApiError(422, "STRUCTURE_NOT_RECOGNISED",
                           "Could not read a chemical structure from this image. Try a clearer, closely cropped image, or type the name or SMILES.")
        smiles = ocr["smiles"]
        confidence = ocr["confidence"]
        source = "image"
        # Stray marks in a picture are often read as extra atoms. Keep the main molecule.
        try:
            smiles, dropped = split_largest_fragment(smiles)
        except InvalidSmilesError:
            dropped = []      # the analysis step below reports an unreadable structure
        if dropped:
            counts = Counter(dropped)
            pieces = ", ".join(f"{frag} x{n}" if n > 1 else frag for frag, n in counts.items())
            warnings.append(f"Ignored extra pieces that were probably noise in the image: {pieces}. "
                            "If your drawing really contains more than one molecule, enter the SMILES instead.")

    # --- SMILES analysis (also the second half of the name and image paths) ---
    if len(smiles) > MAX_SMILES_LENGTH:
        if source == "image":
            raise ApiError(422, "STRUCTURE_NOT_RECOGNISED", "The structure read from the image is not usable.")
        raise ApiError(422, "INVALID_SMILES", "SMILES string is too long.")
    try:
        analysis = analyze_smiles(smiles)
    except InvalidSmilesError as e:
        if source == "name":
            raise ApiError(502, "LOOKUP_FAILED", "PubChem returned a structure that could not be read.")
        if source == "image":
            raise ApiError(422, "STRUCTURE_NOT_RECOGNISED",
                           "The structure read from the image was not a valid molecule. Try a clearer image, or correct the SMILES and resubmit.",
                           extra={"smiles": smiles})
        raise ApiError(422, "INVALID_SMILES", str(e))

    if source == "image" and confidence is not None and confidence < ocsr.LOW_CONFIDENCE:
        warnings.append(f"The structure was read from the image with low confidence ({confidence:.0%}). "
                        "Check that it matches your drawing, and correct the SMILES if it does not.")

    # --- enrich with PubChem data (optional; never breaks the response) ---
    if source in ("smiles", "image"):
        try:
            pubchem_data = pubchem.lookup_by_smiles(analysis["canonical_smiles"])
        except pubchem.PubChemUnavailable:
            warnings.append("PubChem could not be reached, so the IUPAC name and some details are missing.")

    if "." in analysis["canonical_smiles"]:
        warnings.append("This input contains more than one molecule (for example a salt or mixture). Results describe them combined.")

    detected = analysis["functional_groups"]
    if covers_everything(board, grade):
        # Classes 11 and 12: nothing is gated, since many students also prepare for entrance exams.
        in_syllabus, out_of_syllabus = list(detected), []
    else:
        relevant = relevant_groups(board, grade)
        in_syllabus = [g for g in detected if g in relevant]
        out_of_syllabus = [g for g in detected if g not in relevant]
    if out_of_syllabus:
        names = ", ".join(g.replace("_", " ") for g in out_of_syllabus)
        warnings.append(f"Beyond the Class {grade} syllabus (shown for interest): {names}.")

    try:
        properties = generate_explanations(analysis, pubchem_data, board, grade)
    except Exception:
        # Never let the explanation step break the whole response.
        properties = []
        warnings.append("Explanations are temporarily unavailable.")

    return {
        "smiles": analysis["canonical_smiles"],
        "source": source,
        "confidence": round(confidence, 3) if confidence is not None else None,
        "iupac_name": pubchem_data.get("iupac_name") if pubchem_data else None,
        "common_name": pubchem_data.get("title") if pubchem_data else None,
        "formula": analysis["formula"],
        "board": board,
        "grade": grade,
        "structure_svg": structure_svg(analysis["canonical_smiles"]),
        "analysis": analysis,
        "pubchem": pubchem_data,
        "relevant_groups": in_syllabus,
        "out_of_syllabus_groups": out_of_syllabus,
        "properties": properties,
        "warnings": warnings,
    }


# Test page for trying the API (and pasting screenshots) without building a frontend:
#   http://localhost:8000/demo/
# Safe to delete the demo/ folder; the mount is skipped if it is missing.
_DEMO_DIR = Path(__file__).with_name("demo")
if _DEMO_DIR.is_dir():
    app.mount("/demo", StaticFiles(directory=str(_DEMO_DIR), html=True), name="demo")
