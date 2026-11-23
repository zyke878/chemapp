"""Chemistry engine.

Turns a SMILES string into a structured analysis dict using RDKit.
No internet, no models: pure local computation.

Usage:
    from chem import analyze_smiles, InvalidSmilesError
    result = analyze_smiles("CCO")
"""
from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, Lipinski, rdMolDescriptors
from rdkit.Chem.Draw import rdMolDraw2D

# Keep RDKit's own console warnings out of the server logs;
# we report invalid input ourselves via InvalidSmilesError.
RDLogger.DisableLog("rdApp.*")


class InvalidSmilesError(ValueError):
    """Raised when a SMILES string cannot be parsed into a molecule."""


# ---------------------------------------------------------------------------
# Functional groups detected by substructure (SMARTS).
# The KEYS are the shared contract with Person B (see CONTRACT.md).
# To add a group: add one line here, one test in test_chem.py, and list it
# in syllabus.json for the grades where it is taught.
# ---------------------------------------------------------------------------
_AMIDE_LIKE = "!$(N[C,S]=[O,S,N])"  # exclude amides, sulfonamides, amidines

FUNCTIONAL_GROUP_SMARTS = {
    # -OH on a saturated carbon (excludes phenols and carboxylic acids)
    "alcohol": "[CX4][OX2H]",
    # -OH on an aromatic carbon
    "phenol": "[OX2H]c",
    # C-O-C, both carbons sp3 or aromatic. Acetal/hemiacetal oxygens
    # (e.g. the ring oxygen in glucose) are removed by _is_true_ether().
    "ether": "[OD2]([CX4,c])[CX4,c]",
    # R-CHO, plus formaldehyde
    "aldehyde": "[$([CX3H1](=O)[#6]),$([CX3H2]=O)]",
    # C(=O) bonded to two carbons
    "ketone": "[#6][CX3](=O)[#6]",
    "carboxylic_acid": "[CX3](=O)[OX2H1]",
    # Carbonyl carbon needs a carbon neighbour or one H (excludes carbonates, ureas)
    "ester": "[CX3;$([CX3][#6]),$([CX3H1])](=O)[OX2][#6]",
    "amide": "[CX3;$([CX3][#6]),$([CX3H1])](=O)[NX3]",
    # Amines: nitrogen not attached to a carbonyl/sulfonyl/imine carbon
    "primary_amine": f"[NX3;H2;{_AMIDE_LIKE}][#6]",
    "secondary_amine": f"[NX3;H1;{_AMIDE_LIKE}]([#6])[#6]",
    "tertiary_amine": f"[NX3;H0;{_AMIDE_LIKE}]([#6])([#6])[#6]",
    # Halogen on a saturated carbon / on an aromatic carbon
    "haloalkane": "[CX4][F,Cl,Br,I]",
    "haloarene": "c[F,Cl,Br,I]",
    # Unsaturation (aliphatic carbons only, so benzene rings do not count)
    "alkene": "C=C",
    "alkyne": "C#C",
    "diazonium_salt": "[#6][N+]#N",
    # Free alpha-amino acid, neutral or zwitterion (peptides do not match)
    "amino_acid": (
        "[$([NX3;H2,H1;!$(NC=O)]),$([NX4+;H3,H2])]"
        "[CX4][CX3](=O)[OX2H1,OX1-]"
    ),
}

# Keys detected by whole-molecule rules instead of a single SMARTS pattern.
#   alkane       acyclic saturated hydrocarbon
#   cycloalkane  saturated hydrocarbon containing a ring
#   arene        hydrocarbon containing a benzene ring
#   carbohydrate sugar (monosaccharide, or disaccharide-type glycoside)
MOLECULE_LEVEL_KEYS = ["alkane", "cycloalkane", "arene", "carbohydrate"]

GROUP_KEYS = sorted(set(FUNCTIONAL_GROUP_SMARTS) | set(MOLECULE_LEVEL_KEYS))

# Compile once at import time so every request is fast.
_COMPILED_PATTERNS = {}
for _name, _smarts in FUNCTIONAL_GROUP_SMARTS.items():
    _patt = Chem.MolFromSmarts(_smarts)
    if _patt is None:
        raise RuntimeError(f"Bad SMARTS for '{_name}': {_smarts}")
    _COMPILED_PATTERNS[_name] = _patt

_BENZENE = Chem.MolFromSmarts("c1ccccc1")
_HEMIACETAL = Chem.MolFromSmarts("[CX4;R]([OX2H])[OX2;R][#6]")      # sugar ring, free anomeric OH
_RING_ACETAL = Chem.MolFromSmarts("[CX4;R]([OX2;R][#6])[OX2H0][#6]")  # glycosidic link (e.g. sucrose)


def parse_smiles(smiles):
    """Parse a SMILES string, raising InvalidSmilesError if it is unusable."""
    if smiles is None or not str(smiles).strip():
        raise InvalidSmilesError("Empty SMILES string.")
    mol = Chem.MolFromSmiles(str(smiles).strip())
    if mol is None:
        raise InvalidSmilesError(f"Could not parse SMILES: {smiles!r}")
    if mol.GetNumHeavyAtoms() == 0:
        raise InvalidSmilesError("Molecule has no atoms.")
    return mol


def _is_true_ether(mol, match):
    """An ether oxygen whose carbons carry no other oxygen.

    This drops acetal and hemiacetal oxygens (for example the ring oxygen of
    glucose), which behave differently from ordinary ethers.
    """
    o_idx, c1, c2 = match
    for c in (c1, c2):
        for n in mol.GetAtomWithIdx(c).GetNeighbors():
            if n.GetAtomicNum() == 8 and n.GetIdx() != o_idx:
                return False
    return True


def _all_atoms_in(mol, atomic_numbers):
    return all(a.GetAtomicNum() in atomic_numbers for a in mol.GetAtoms())


def _is_saturated_hydrocarbon(mol):
    return (
        _all_atoms_in(mol, (1, 6))
        and all(b.GetBondType() == Chem.BondType.SINGLE for b in mol.GetBonds())
    )


def _is_carbohydrate(mol, counts):
    """Monosaccharide or glycoside built only from C, H and O."""
    if not _all_atoms_in(mol, (1, 6, 8)):
        return False
    if any(k in counts for k in ("carboxylic_acid", "ester", "alkene", "alkyne")):
        return False
    if any(a.GetIsAromatic() for a in mol.GetAtoms()):
        return False
    oh = counts.get("alcohol", 0)
    has_carbonyl = "aldehyde" in counts or "ketone" in counts
    no_rings = mol.GetRingInfo().NumRings() == 0

    if has_carbonyl and no_rings and oh >= 2:          # open-chain aldose / ketose
        return True
    if mol.HasSubstructMatch(_HEMIACETAL) and oh >= 3:  # ring form with free anomeric OH
        return True
    if mol.HasSubstructMatch(_RING_ACETAL) and oh >= 4:  # glycoside, e.g. sucrose
        return True
    return False


def detect_functional_groups(mol):
    """Return {group_key: number_of_occurrences} for groups found in mol.

    For whole-molecule keys (alkane, cycloalkane, arene, carbohydrate) the
    count is 1, except arene which counts benzene rings.
    """
    counts = {}
    for name, patt in _COMPILED_PATTERNS.items():
        matches = mol.GetSubstructMatches(patt)
        if name == "ether":
            matches = [m for m in matches if _is_true_ether(mol, m)]
        if matches:
            counts[name] = len(matches)

    if _is_saturated_hydrocarbon(mol):
        counts["cycloalkane" if mol.GetRingInfo().NumRings() else "alkane"] = 1
    if _all_atoms_in(mol, (1, 6)):
        n_benzene = len(mol.GetSubstructMatches(_BENZENE))
        if n_benzene:
            counts["arene"] = n_benzene
    if _is_carbohydrate(mol, counts):
        counts["carbohydrate"] = 1

    return dict(sorted(counts.items()))


def _hybridisation_counts(mol):
    """Count heavy atoms by hybridisation (sp, sp2, sp3). Others are skipped."""
    wanted = {
        Chem.HybridizationType.SP: "sp",
        Chem.HybridizationType.SP2: "sp2",
        Chem.HybridizationType.SP3: "sp3",
    }
    counts = {"sp": 0, "sp2": 0, "sp3": 0}
    for atom in mol.GetAtoms():
        label = wanted.get(atom.GetHybridization())
        if label:
            counts[label] += 1
    return counts


def analyze_smiles(smiles):
    """Analyse a SMILES string. Raises InvalidSmilesError on bad input.

    Returned dict (shared contract with Person B, see CONTRACT.md):
        canonical_smiles   str
        formula            str
        mol_weight         float   (rounded to 2 dp)
        hbond_donors       int
        hbond_acceptors    int
        rings              int
        aromatic_rings     int
        stereocentres      int
        functional_groups  list[str]  (keys from GROUP_KEYS)
        group_counts       dict[str, int]
        hybridisation      dict[str, int]  (heavy-atom counts: sp, sp2, sp3)
    """
    mol = parse_smiles(smiles)
    group_counts = detect_functional_groups(mol)
    stereo = Chem.FindMolChiralCenters(mol, includeUnassigned=True)

    return {
        "canonical_smiles": Chem.MolToSmiles(mol),
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "mol_weight": round(Descriptors.MolWt(mol), 2),
        "hbond_donors": Lipinski.NumHDonors(mol),
        "hbond_acceptors": Lipinski.NumHAcceptors(mol),
        "rings": rdMolDescriptors.CalcNumRings(mol),
        "aromatic_rings": rdMolDescriptors.CalcNumAromaticRings(mol),
        "stereocentres": len(stereo),
        "functional_groups": sorted(group_counts),
        "group_counts": group_counts,
        "hybridisation": _hybridisation_counts(mol),
    }


def split_largest_fragment(smiles):
    """Return (largest_fragment_smiles, [other_fragment_smiles]).

    Image recognition often adds stray pieces (single atoms, H2) from noise or
    text near the structure. Keeping the largest fragment removes them.
    Single-fragment input is returned unchanged with an empty list.
    """
    mol = parse_smiles(smiles)
    frags = Chem.GetMolFrags(mol, asMols=True)
    if len(frags) <= 1:
        return smiles, []
    ordered = sorted(frags, key=lambda m: m.GetNumHeavyAtoms(), reverse=True)
    return Chem.MolToSmiles(ordered[0]), [Chem.MolToSmiles(m) for m in ordered[1:]]


def structure_svg(smiles, width=360, height=260):
    """Draw the molecule as an SVG string (white background), or None on failure.

    The frontend shows this next to the result so a student can check that the
    structure the app understood is the one they meant (important for images).
    """
    try:
        mol = parse_smiles(smiles)
        from rdkit.Chem import rdDepictor
        rdDepictor.Compute2DCoords(mol)
        drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
        drawer.DrawMolecule(mol)
        drawer.FinishDrawing()
        return drawer.GetDrawingText()
    except Exception:
        return None
