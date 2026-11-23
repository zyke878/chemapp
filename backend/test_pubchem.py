"""Run with:  pytest -v   (from the backend/ folder). Uses fake responses, no internet."""
import pytest
import requests

import pubchem


class FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("bad json")
        return self._payload


def table(**props):
    return {"PropertyTable": {"Properties": [props]}}


ASPIRIN = table(CID=2244, SMILES="CC(=O)OC1=CC=CC=C1C(=O)O", IUPACName="2-acetyloxybenzoic acid",
                Title="Aspirin", MolecularFormula="C9H8O4", MolecularWeight="180.16",
                XLogP=1.2, TPSA=63.6)


@pytest.fixture(autouse=True)
def fresh_cache():
    pubchem.clear_cache()
    yield
    pubchem.clear_cache()


def patch_request(monkeypatch, responder):
    calls = []

    def fake(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return responder(len(calls), method, url, kwargs)

    monkeypatch.setattr(pubchem, "_request", fake)
    return calls


def test_name_lookup_parses_result(monkeypatch):
    calls = patch_request(monkeypatch, lambda n, m, u, k: FakeResponse(200, ASPIRIN))
    r = pubchem.lookup_by_name("  Aspirin ")
    assert r == {"cid": 2244, "iupac_name": "2-acetyloxybenzoic acid", "title": "Aspirin",
                 "smiles": "CC(=O)OC1=CC=CC=C1C(=O)O", "formula": "C9H8O4",
                 "mol_weight": 180.16, "xlogp": 1.2, "tpsa": 63.6}
    assert calls[0][0] == "GET" and "/compound/name/aspirin/" in calls[0][1]


def test_smiles_lookup_uses_post_body(monkeypatch):
    calls = patch_request(monkeypatch, lambda n, m, u, k: FakeResponse(200, ASPIRIN))
    pubchem.lookup_by_smiles("CC(=O)Oc1ccccc1C(=O)O")
    method, url, kwargs = calls[0]
    assert method == "POST" and kwargs["data"] == {"smiles": "CC(=O)Oc1ccccc1C(=O)O"}
    assert "CC(=O)" not in url


def test_legacy_smiles_key_is_understood(monkeypatch):
    legacy = table(CID=702, CanonicalSMILES="CCO", IUPACName="ethanol", MolecularFormula="C2H6O", MolecularWeight="46.07")
    patch_request(monkeypatch, lambda n, m, u, k: FakeResponse(200, legacy))
    r = pubchem.lookup_by_name("ethanol")
    assert r["smiles"] == "CCO" and r["xlogp"] is None and r["title"] is None


def test_not_found_returns_none(monkeypatch):
    patch_request(monkeypatch, lambda n, m, u, k: FakeResponse(404))
    assert pubchem.lookup_by_name("zzzznotachemical") is None


def test_falls_back_to_older_property_names_on_400(monkeypatch):
    def responder(n, m, u, k):
        return FakeResponse(400) if n == 1 else FakeResponse(200, ASPIRIN)
    calls = patch_request(monkeypatch, responder)
    assert pubchem.lookup_by_name("aspirin")["cid"] == 2244
    assert len(calls) == 2 and "CanonicalSMILES" in calls[1][1]


def test_all_400_returns_none(monkeypatch):
    patch_request(monkeypatch, lambda n, m, u, k: FakeResponse(400))
    assert pubchem.lookup_by_smiles("not valid") is None


@pytest.mark.parametrize("status", [429, 500, 503])
def test_server_errors_raise_unavailable(monkeypatch, status):
    patch_request(monkeypatch, lambda n, m, u, k: FakeResponse(status))
    with pytest.raises(pubchem.PubChemUnavailable):
        pubchem.lookup_by_name("aspirin")


def test_timeout_raises_unavailable(monkeypatch):
    def responder(n, m, u, k):
        raise requests.Timeout("slow")
    patch_request(monkeypatch, responder)
    with pytest.raises(pubchem.PubChemUnavailable):
        pubchem.lookup_by_name("aspirin")


def test_bad_json_raises_unavailable(monkeypatch):
    patch_request(monkeypatch, lambda n, m, u, k: FakeResponse(200, bad_json=True))
    with pytest.raises(pubchem.PubChemUnavailable):
        pubchem.lookup_by_name("aspirin")


def test_results_are_cached(monkeypatch):
    calls = patch_request(monkeypatch, lambda n, m, u, k: FakeResponse(200, ASPIRIN))
    pubchem.lookup_by_name("Aspirin")
    pubchem.lookup_by_name("aspirin")
    pubchem.lookup_by_name("  ASPIRIN  ")
    assert len(calls) == 1


def test_not_found_is_cached_but_outage_is_not(monkeypatch):
    calls = patch_request(monkeypatch, lambda n, m, u, k: FakeResponse(404))
    pubchem.lookup_by_name("nothing"); pubchem.lookup_by_name("nothing")
    assert len(calls) == 1

    pubchem.clear_cache()
    state = {"down": True}

    def responder(n, m, u, k):
        return FakeResponse(503) if state["down"] else FakeResponse(200, ASPIRIN)
    patch_request(monkeypatch, responder)
    with pytest.raises(pubchem.PubChemUnavailable):
        pubchem.lookup_by_name("aspirin")
    state["down"] = False
    assert pubchem.lookup_by_name("aspirin")["cid"] == 2244


def test_empty_input_makes_no_request(monkeypatch):
    calls = patch_request(monkeypatch, lambda n, m, u, k: FakeResponse(200, ASPIRIN))
    assert pubchem.lookup_by_name("   ") is None
    assert pubchem.lookup_by_smiles("") is None
    assert calls == []
