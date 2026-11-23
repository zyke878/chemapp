"""PubChem lookup (Phase 4), using the PUG-REST API through `requests`.

    lookup_by_name("aspirin")   -> dict or None (not found)
    lookup_by_smiles("CCO")     -> dict or None (not found)
Both raise PubChemUnavailable when PubChem cannot be reached or errors out,
so callers can fall back to RDKit-only results.

Returned dict:
    {"cid": int | None, "iupac_name": str | None, "title": str | None,
     "smiles": str | None, "formula": str | None, "mol_weight": float | None,
     "xlogp": float | None, "tpsa": float | None}
These are PubChem's computed values, not experimental measurements.

Live check from the backend/ folder:
    python pubchem.py name aspirin
    python pubchem.py smiles CCO
"""
import threading
import time
from urllib.parse import quote

import requests

BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
TIMEOUT = 8            # seconds
MIN_INTERVAL = 0.25    # PubChem asks for at most 5 requests per second
MAX_CACHE = 5000

# PubChem has renamed its SMILES properties. Try the current names first,
# then older ones, then a minimal set. A 400 means "property name not accepted".
_PROPERTY_SETS = [
    "SMILES,IUPACName,Title,MolecularFormula,MolecularWeight,XLogP,TPSA",
    "CanonicalSMILES,IUPACName,Title,MolecularFormula,MolecularWeight,XLogP,TPSA",
    "CanonicalSMILES,IUPACName,MolecularFormula,MolecularWeight",
]
_SMILES_KEYS = ("SMILES", "IsomericSMILES", "ConnectivitySMILES", "CanonicalSMILES")

_lock = threading.Lock()
_last_call = 0.0
_cache = {}


class PubChemUnavailable(Exception):
    """PubChem could not be reached or returned a server-side error."""


def _request(method, url, **kwargs):
    """One throttled HTTP call. Tests replace this function."""
    global _last_call
    with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
    return requests.request(
        method, url, timeout=TIMEOUT,
        headers={"User-Agent": "chemprop/0.1 (student project)"}, **kwargs,
    )


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse(payload):
    try:
        props = payload["PropertyTable"]["Properties"][0]
    except (KeyError, IndexError, TypeError):
        return None
    smiles = next((props[k] for k in _SMILES_KEYS if props.get(k)), None)
    return {
        "cid": props.get("CID"),
        "iupac_name": props.get("IUPACName"),
        "title": props.get("Title"),
        "smiles": smiles,
        "formula": props.get("MolecularFormula"),
        "mol_weight": _to_float(props.get("MolecularWeight")),
        "xlogp": _to_float(props.get("XLogP")),
        "tpsa": _to_float(props.get("TPSA")),
    }


def _fetch(kind, value):
    for props in _PROPERTY_SETS:
        try:
            if kind == "name":
                url = f"{BASE}/compound/name/{quote(value, safe='')}/property/{props}/JSON"
                resp = _request("GET", url)
            else:  # SMILES goes in a POST body because it can contain / # + characters
                url = f"{BASE}/compound/smiles/property/{props}/JSON"
                resp = _request("POST", url, data={"smiles": value})
        except requests.RequestException as e:
            raise PubChemUnavailable(str(e)) from e

        if resp.status_code == 200:
            try:
                return _parse(resp.json())
            except ValueError as e:
                raise PubChemUnavailable("PubChem returned invalid JSON") from e
        if resp.status_code == 404:
            return None
        if resp.status_code == 400:
            continue
        raise PubChemUnavailable(f"PubChem returned HTTP {resp.status_code}")
    return None


def _cached_lookup(kind, key_value):
    key = (kind, key_value)
    if key in _cache:
        return _cache[key]
    result = _fetch(kind, key_value)          # raises on outage, so outages are not cached
    if len(_cache) >= MAX_CACHE:
        _cache.clear()
    _cache[key] = result
    return result


def lookup_by_name(name):
    name = " ".join(str(name).split())
    if not name:
        return None
    return _cached_lookup("name", name.lower())


def lookup_by_smiles(smiles):
    smiles = str(smiles).strip()
    if not smiles:
        return None
    return _cached_lookup("smiles", smiles)


def clear_cache():
    _cache.clear()


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) != 3 or sys.argv[1] not in ("name", "smiles"):
        sys.exit("Usage: python pubchem.py name aspirin   |   python pubchem.py smiles CCO")
    fn = lookup_by_name if sys.argv[1] == "name" else lookup_by_smiles
    try:
        print(json.dumps(fn(sys.argv[2]), indent=2))
    except PubChemUnavailable as e:
        sys.exit(f"PubChem unavailable: {e}")
