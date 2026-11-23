"""Run with:  pytest -v   (from the backend/ folder)"""
import pytest
from fastapi.testclient import TestClient
from main import app

import ocsr
import pubchem

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_real_pubchem(monkeypatch):
    """API tests never touch the internet. Individual tests override these."""
    monkeypatch.setattr(pubchem, "lookup_by_smiles", lambda s: None)
    monkeypatch.setattr(pubchem, "lookup_by_name", lambda n: None)
    monkeypatch.setattr(ocsr, "is_available", lambda: False)


def post(**fields):
    return client.post("/api/analyze", data=fields)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_valid_smiles():
    r = post(smiles="CCO", grade="12", board="cbse")
    assert r.status_code == 200
    body = r.json()
    assert body["smiles"] == "CCO"
    assert body["source"] == "smiles"
    assert body["formula"] == "C2H6O"
    assert body["analysis"]["functional_groups"] == ["alcohol"]
    assert body["properties"] == []          # stub until Person B's module exists


def test_invalid_smiles():
    r = post(smiles="not a smiles", grade="12", board="CBSE")
    assert r.status_code == 422
    assert r.json()["code"] == "INVALID_SMILES"


@pytest.mark.parametrize("grade", ["3", "9", "13"])
def test_bad_grade(grade):
    r = post(smiles="CCO", grade=grade, board="CBSE")
    assert r.status_code == 422 and r.json()["code"] == "INVALID_GRADE"


@pytest.mark.parametrize("grade", ["10", "11", "12"])
def test_supported_grades(grade):
    assert post(smiles="CCO", grade=grade, board="CBSE").status_code == 200


def test_bad_board():
    r = post(smiles="CCO", grade="12", board="ICSE")
    assert r.status_code == 422 and r.json()["code"] == "INVALID_BOARD"


def test_config(monkeypatch):
    assert client.get("/api/config").json() == {"boards": ["CBSE"], "grades": [10, 11, 12], "image_input": False}
    monkeypatch.setattr(ocsr, "is_available", lambda: True)
    assert client.get("/api/config").json()["image_input"] is True


def test_relevant_groups_by_grade():
    r10 = post(smiles="CCO", grade="10", board="CBSE").json()
    assert r10["relevant_groups"] == ["alcohol"] and r10["out_of_syllabus_groups"] == []
    # phenol is not taught in Class 10: reported separately, with a warning
    p10 = post(smiles="Oc1ccccc1", grade="10", board="CBSE").json()
    assert p10["relevant_groups"] == [] and p10["out_of_syllabus_groups"] == ["phenol"]
    assert any("phenol" in w and "Beyond the Class 10 syllabus" in w for w in p10["warnings"])
    p12 = post(smiles="Oc1ccccc1", grade="12", board="CBSE").json()
    assert p12["relevant_groups"] == ["phenol"] and p12["out_of_syllabus_groups"] == []


def test_classes_11_and_12_are_not_gated():
    # hexane (alkane) is in Class 10 and 11 chapters but not in the Class 12 chapter lists;
    # glycine/amino_acid is only in the Class 12 list. Neither is gated for 11 or 12.
    for grade in ("11", "12"):
        h = post(smiles="CCCCCC", grade=grade, board="CBSE").json()
        assert h["relevant_groups"] == ["alkane"] and h["out_of_syllabus_groups"] == []
        g = post(smiles="NCC(=O)O", grade=grade, board="CBSE").json()
        assert g["out_of_syllabus_groups"] == [] and "amino_acid" in g["relevant_groups"]
        assert g["warnings"] == []
    # Class 10 is still gated, but only as a soft note
    g10 = post(smiles="NCC(=O)O", grade="10", board="CBSE").json()
    assert "amino_acid" in g10["out_of_syllabus_groups"] and g10["relevant_groups"] == ["carboxylic_acid"]
    assert any("shown for interest" in w for w in g10["warnings"])


def test_missing_fields():
    r = client.post("/api/analyze", data={"smiles": "CCO"})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_REQUEST"


def test_no_input():
    r = post(grade="12", board="CBSE")
    assert r.status_code == 422 and r.json()["code"] == "INVALID_INPUT"


def test_two_inputs():
    r = post(smiles="CCO", name="ethanol", grade="12", board="CBSE")
    assert r.status_code == 422 and r.json()["code"] == "INVALID_INPUT"


ETHANOL = {"cid": 702, "iupac_name": "ethanol", "title": "Ethanol", "smiles": "CCO",
           "formula": "C2H6O", "mol_weight": 46.07, "xlogp": -0.1, "tpsa": 20.2}


def test_name_lookup_success(monkeypatch):
    monkeypatch.setattr(pubchem, "lookup_by_name", lambda n: ETHANOL)
    r = post(name="ethanol", grade="12", board="CBSE")
    body = r.json()
    assert r.status_code == 200
    assert body["source"] == "name" and body["smiles"] == "CCO"
    assert body["iupac_name"] == "ethanol" and body["common_name"] == "Ethanol"
    assert body["pubchem"]["cid"] == 702
    assert body["analysis"]["functional_groups"] == ["alcohol"]


def test_name_not_found(monkeypatch):
    monkeypatch.setattr(pubchem, "lookup_by_name", lambda n: None)
    r = post(name="zzzz", grade="12", board="CBSE")
    assert r.status_code == 404 and r.json()["code"] == "NAME_NOT_FOUND"


def test_name_lookup_pubchem_down(monkeypatch):
    def down(n):
        raise pubchem.PubChemUnavailable("down")
    monkeypatch.setattr(pubchem, "lookup_by_name", down)
    r = post(name="ethanol", grade="12", board="CBSE")
    assert r.status_code == 503 and r.json()["code"] == "PUBCHEM_UNAVAILABLE"


def test_name_returns_unreadable_structure(monkeypatch):
    monkeypatch.setattr(pubchem, "lookup_by_name", lambda n: {**ETHANOL, "smiles": "C(C"})
    r = post(name="ethanol", grade="12", board="CBSE")
    assert r.status_code == 502 and r.json()["code"] == "LOOKUP_FAILED"


def test_smiles_path_is_enriched_with_pubchem(monkeypatch):
    monkeypatch.setattr(pubchem, "lookup_by_smiles", lambda s: ETHANOL)
    body = post(smiles="OCC", grade="12", board="CBSE").json()
    assert body["source"] == "smiles" and body["iupac_name"] == "ethanol"


def test_smiles_path_survives_pubchem_outage(monkeypatch):
    def down(s):
        raise pubchem.PubChemUnavailable("down")
    monkeypatch.setattr(pubchem, "lookup_by_smiles", down)
    r = post(smiles="CCO", grade="12", board="CBSE")
    assert r.status_code == 200
    assert r.json()["iupac_name"] is None and r.json()["pubchem"] is None
    assert any("PubChem" in w for w in r.json()["warnings"])


def test_pubchem_data_is_passed_to_explanations(monkeypatch):
    import main
    seen = {}
    def spy(analysis, pubchem_data, board, grade):
        seen["pubchem"] = pubchem_data
        return []
    monkeypatch.setattr(main, "generate_explanations", spy)
    monkeypatch.setattr(pubchem, "lookup_by_smiles", lambda s: ETHANOL)
    post(smiles="CCO", grade="12", board="CBSE")
    assert seen["pubchem"]["iupac_name"] == "ethanol"


def post_image(content=b"fake-image-bytes", **fields):
    data = {"grade": "12", "board": "CBSE", **fields}
    return client.post("/api/analyze", data=data, files={"image": ("structure.png", content, "image/png")})


def fake_ocr(smiles="CCO", confidence=0.97):
    return lambda image_bytes: {"smiles": smiles, "confidence": confidence}


def test_image_success(monkeypatch):
    monkeypatch.setattr(ocsr, "image_to_smiles", fake_ocr("OCC", 0.97))
    r = post_image()
    body = r.json()
    assert r.status_code == 200
    assert body["source"] == "image" and body["smiles"] == "CCO" and body["confidence"] == 0.97
    assert body["analysis"]["functional_groups"] == ["alcohol"]
    assert body["warnings"] == []


def test_image_low_confidence_warns(monkeypatch):
    monkeypatch.setattr(ocsr, "image_to_smiles", fake_ocr("CCO", 0.4))
    body = post_image().json()
    assert any("low confidence" in w for w in body["warnings"])
    assert body["confidence"] == 0.4


def test_image_path_is_enriched_with_pubchem(monkeypatch):
    monkeypatch.setattr(ocsr, "image_to_smiles", fake_ocr())
    monkeypatch.setattr(pubchem, "lookup_by_smiles", lambda s: ETHANOL)
    assert post_image().json()["iupac_name"] == "ethanol"


def test_image_not_a_valid_molecule(monkeypatch):
    monkeypatch.setattr(ocsr, "image_to_smiles", fake_ocr("C(C", 0.9))
    r = post_image()
    assert r.status_code == 422
    assert r.json()["code"] == "STRUCTURE_NOT_RECOGNISED" and r.json()["smiles"] == "C(C"


@pytest.mark.parametrize("exc,status,code", [
    (ocsr.InvalidImage("bad"), 422, "INVALID_IMAGE"),
    (ocsr.OcsrUnavailable("down"), 503, "OCR_UNAVAILABLE"),
    (ocsr.OcsrFailed("nothing"), 422, "STRUCTURE_NOT_RECOGNISED"),
])
def test_image_errors(monkeypatch, exc, status, code):
    def boom(image_bytes):
        raise exc
    monkeypatch.setattr(ocsr, "image_to_smiles", boom)
    r = post_image()
    assert r.status_code == status and r.json()["code"] == code


def test_image_too_large(monkeypatch):
    monkeypatch.setattr(ocsr, "image_to_smiles", fake_ocr())
    r = post_image(content=b"x" * (10 * 1024 * 1024 + 1))
    assert r.status_code == 413 and r.json()["code"] == "IMAGE_TOO_LARGE"


def test_image_and_smiles_together_rejected(monkeypatch):
    monkeypatch.setattr(ocsr, "image_to_smiles", fake_ocr())
    r = post_image(smiles="CCO")
    assert r.status_code == 422 and r.json()["code"] == "INVALID_INPUT"


def test_structure_svg_is_returned():
    body = post(smiles="CCO", grade="12", board="CBSE").json()
    assert "<svg" in body["structure_svg"]


def test_image_noise_fragments_are_dropped(monkeypatch):
    monkeypatch.setattr(ocsr, "image_to_smiles", fake_ocr("CC(=O)Oc1ccccc1C(=O)O.I.I.I.[HH]", 0.9))
    body = post_image().json()
    assert body["smiles"] == "CC(=O)Oc1ccccc1C(=O)O"
    assert body["formula"] == "C9H8O4"
    assert any("Ignored extra pieces" in w and "I x3" in w for w in body["warnings"])


def test_typed_salt_is_not_split():
    body = post(smiles="CC(=O)[O-].[Na+]", grade="12", board="CBSE").json()
    assert "." in body["smiles"]


def test_board_defaults_to_cbse():
    r = client.post("/api/analyze", data={"smiles": "CCO", "grade": "12"})
    assert r.status_code == 200 and r.json()["board"] == "CBSE"
    r = client.post("/api/analyze", data={"smiles": "CCO", "grade": "12", "board": ""})
    assert r.status_code == 200 and r.json()["board"] == "CBSE"


def test_grade_is_still_required():
    r = client.post("/api/analyze", data={"smiles": "CCO"})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_REQUEST"


def test_demo_page_is_served():
    r = client.get("/demo/")
    assert r.status_code == 200 and "Chemprop" in r.text and "chemprop-api.js" in r.text
    js = client.get("/demo/chemprop-api.js")
    assert js.status_code == 200 and "enableImagePaste" in js.text
