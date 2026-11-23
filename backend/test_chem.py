"""Run with:  pytest -v   (from the backend/ folder)"""
import pytest
from chem import analyze_smiles, split_largest_fragment, structure_svg, InvalidSmilesError, GROUP_KEYS

# (name, smiles, groups that MUST be found exactly)
CASES = [
    # --- hydrocarbons ---
    ("methane",           "C",                       {"alkane"}),
    ("hexane",            "CCCCCC",                  {"alkane"}),
    ("cyclohexane",       "C1CCCCC1",                {"cycloalkane"}),
    ("ethene",            "C=C",                     {"alkene"}),
    ("cyclohexene",       "C1=CCCCC1",               {"alkene"}),
    ("ethyne",            "C#C",                     {"alkyne"}),
    ("benzene",           "c1ccccc1",                {"arene"}),
    ("toluene",           "Cc1ccccc1",               {"arene"}),
    ("naphthalene",       "c1ccc2ccccc2c1",          {"arene"}),
    ("styrene",           "C=Cc1ccccc1",             {"alkene", "arene"}),
    # --- alcohols, phenols, ethers ---
    ("ethanol",           "CCO",                     {"alcohol"}),
    ("methanol",          "CO",                      {"alcohol"}),
    ("glycerol",          "OCC(O)CO",                {"alcohol"}),
    ("phenol",            "Oc1ccccc1",               {"phenol"}),
    ("diethyl ether",     "CCOCC",                   {"ether"}),
    ("anisole",           "COc1ccccc1",              {"ether"}),
    ("THF",               "C1CCOC1",                 {"ether"}),
    ("MOM ether (acetal)", "COCOC",                  set()),
    # --- carbonyl compounds ---
    ("acetaldehyde",      "CC=O",                    {"aldehyde"}),
    ("formaldehyde",      "C=O",                     {"aldehyde"}),
    ("benzaldehyde",      "O=Cc1ccccc1",             {"aldehyde"}),
    ("acetone",           "CC(C)=O",                 {"ketone"}),
    ("acetophenone",      "CC(=O)c1ccccc1",          {"ketone"}),
    ("acetic acid",       "CC(=O)O",                 {"carboxylic_acid"}),
    ("benzoic acid",      "OC(=O)c1ccccc1",          {"carboxylic_acid"}),
    ("acrylic acid",      "C=CC(=O)O",               {"alkene", "carboxylic_acid"}),
    ("ethyl acetate",     "CCOC(C)=O",               {"ester"}),
    ("methyl formate",    "COC=O",                   {"ester"}),
    ("acetamide",         "CC(N)=O",                 {"amide"}),
    ("dimethyl carbonate", "COC(=O)OC",              set()),
    ("urea",              "NC(N)=O",                 set()),
    # --- amines ---
    ("methylamine",       "CN",                      {"primary_amine"}),
    ("aniline",           "Nc1ccccc1",               {"primary_amine"}),
    ("dimethylamine",     "CNC",                     {"secondary_amine"}),
    ("trimethylamine",    "CN(C)C",                  {"tertiary_amine"}),
    ("benzenediazonium",  "[N+](#N)c1ccccc1",        {"diazonium_salt"}),
    ("benzenediazonium chloride", "[N+](#N)c1ccccc1.[Cl-]", {"diazonium_salt"}),
    # --- halogen compounds ---
    ("chloroethane",      "CCCl",                    {"haloalkane"}),
    ("chlorobenzene",     "Clc1ccccc1",              {"haloarene"}),
    # --- multi-group molecules ---
    ("lactic acid",       "CC(O)C(=O)O",             {"alcohol", "carboxylic_acid"}),
    ("4-aminophenol",     "Nc1ccc(O)cc1",            {"primary_amine", "phenol"}),
    ("chloroacetone",     "CC(=O)CCl",               {"ketone", "haloalkane"}),
    ("aspirin",           "CC(=O)Oc1ccccc1C(=O)O",   {"carboxylic_acid", "ester"}),
    ("paracetamol",       "CC(=O)Nc1ccc(O)cc1",      {"amide", "phenol"}),
    # --- biomolecules: amino acids ---
    ("glycine",           "NCC(=O)O",                {"amino_acid", "primary_amine", "carboxylic_acid"}),
    ("alanine",           "CC(N)C(=O)O",             {"amino_acid", "primary_amine", "carboxylic_acid"}),
    ("proline",           "OC(=O)C1CCCN1",           {"amino_acid", "secondary_amine", "carboxylic_acid"}),
    ("glycine zwitterion", "[NH3+]CC([O-])=O",       {"amino_acid"}),
    ("Gly-Gly dipeptide", "NCC(=O)NCC(=O)O",         {"amide", "primary_amine", "carboxylic_acid"}),
    # --- biomolecules: carbohydrates (ring oxygen is not reported as an ether) ---
    ("glucose (open)",    "OCC(O)C(O)C(O)C(O)C=O",   {"carbohydrate", "alcohol", "aldehyde"}),
    ("glucopyranose",     "OCC1OC(O)C(O)C(O)C1O",    {"carbohydrate", "alcohol"}),
    ("fructose (open)",   "OCC(=O)C(O)C(O)C(O)CO",   {"carbohydrate", "alcohol", "ketone"}),
    ("fructofuranose",    "OCC1(O)OC(CO)C(O)C1O",    {"carbohydrate", "alcohol"}),
    ("sucrose",           "OCC1OC(OC2(CO)OC(CO)C(O)C2O)C(O)C(O)C1O", {"carbohydrate", "alcohol"}),
    ("glyceraldehyde",    "OCC(O)C=O",               {"carbohydrate", "alcohol", "aldehyde"}),
    ("vitamin C (not a sugar)", "OCC(O)C1OC(=O)C(O)=C1O", {"alcohol", "alkene", "ester"}),
    ("ethylene glycol (not a sugar)", "OCCO",        {"alcohol"}),
]


@pytest.mark.parametrize("name,smiles,expected", CASES, ids=[c[0] for c in CASES])
def test_functional_groups(name, smiles, expected):
    got = set(analyze_smiles(smiles)["functional_groups"])
    assert got == expected, f"{name}: expected {expected}, got {got}"


def test_every_reported_key_is_in_group_keys():
    for _, smiles, _ in CASES:
        for g in analyze_smiles(smiles)["functional_groups"]:
            assert g in GROUP_KEYS


def test_group_counts():
    assert analyze_smiles("OCC(O)CO")["group_counts"]["alcohol"] == 3
    assert analyze_smiles("OCC1OC(O)C(O)C(O)C1O")["group_counts"]["alcohol"] == 5
    assert analyze_smiles("c1ccc2ccccc2c1")["group_counts"]["arene"] == 2


def test_ethanol_descriptors():
    r = analyze_smiles("CCO")
    assert r["canonical_smiles"] == "CCO"
    assert r["formula"] == "C2H6O"
    assert r["mol_weight"] == 46.07
    assert r["hbond_donors"] == 1
    assert r["hbond_acceptors"] == 1
    assert r["rings"] == 0
    assert r["hybridisation"] == {"sp": 0, "sp2": 0, "sp3": 3}


def test_benzene_aromatic():
    r = analyze_smiles("c1ccccc1")
    assert r["rings"] == 1 and r["aromatic_rings"] == 1
    assert r["hybridisation"]["sp2"] == 6


def test_stereocentre():
    assert analyze_smiles("C[C@H](N)C(=O)O")["stereocentres"] == 1   # alanine
    assert analyze_smiles("CC(O)C(=O)O")["stereocentres"] == 1       # unspecified still counted
    assert analyze_smiles("CCO")["stereocentres"] == 0


def test_canonicalisation_is_consistent():
    a = analyze_smiles("OCC")["canonical_smiles"]
    b = analyze_smiles("C(O)C")["canonical_smiles"]
    assert a == b == "CCO"


@pytest.mark.parametrize("bad", ["", "   ", "not a smiles", "C(C", "XyZ123"])
def test_invalid_smiles(bad):
    with pytest.raises(InvalidSmilesError):
        analyze_smiles(bad)


def test_none_input():
    with pytest.raises(InvalidSmilesError):
        analyze_smiles(None)


def test_structure_svg():
    svg = structure_svg("CC(=O)Oc1ccccc1C(=O)O")
    assert "<svg" in svg and "</svg>" in svg
    assert structure_svg("not a smiles") is None


def test_split_largest_fragment_removes_noise():
    kept, dropped = split_largest_fragment("CC(=O)Oc1ccccc1C(=O)O.I.I.I.[HH]")
    assert kept == "CC(=O)Oc1ccccc1C(=O)O"
    assert sorted(dropped) == ["I", "I", "I", "[HH]"]


def test_split_largest_fragment_leaves_single_molecule_alone():
    assert split_largest_fragment("OCC") == ("OCC", [])


def test_split_largest_fragment_invalid():
    with pytest.raises(InvalidSmilesError):
        split_largest_fragment("C(C")
