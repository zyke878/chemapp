# CONTRACT: Person A (engine/API) <-> Person B (explanations)

Change this file first, then the code. Both people agree before editing it.

## 1. Scope
- Board: CBSE only. Grades: 10, 11, 12. Source: CBSE 2026-27 syllabus PDFs.
- Organic chemistry first. Biomolecules limited to small ones (monosaccharides, amino acids, simple vitamins).
- Person A owns: `chem.py`, `syllabus.json` / `syllabus.py`, `main.py`, PubChem, image input.
- Person B owns: `explain.py` (AI-generated explanation of WHY each property arises, plus checks).

## 2. Group keys (the only strings used anywhere)
Substructure-based: `alcohol, phenol, ether, aldehyde, ketone, carboxylic_acid, ester, amide,
primary_amine, secondary_amine, tertiary_amine, haloalkane, haloarene, alkene, alkyne,
diazonium_salt, amino_acid`

Whole-molecule: `alkane` (acyclic saturated hydrocarbon), `cycloalkane`, `arene` (hydrocarbon with a
benzene ring), `carbohydrate` (sugar).

Notes for Person B:
- `amino_acid` and `carbohydrate` are compound classes and overlap with functional groups
  (glycine reports `amino_acid`, `primary_amine` and `carboxylic_acid`).
- The ring oxygen of a sugar is NOT reported as `ether` (it is a hemiacetal/acetal oxygen).
- `arene` is only for hydrocarbons. For substituted benzene rings use `analysis.aromatic_rings`.
- Vitamins, hormones, nucleic acids and enzymes are not detected as classes. Vitamins get explanations
  from their functional groups only.

## 3. Analysis dict (`chem.analyze_smiles(smiles)`)
```
canonical_smiles: str       formula: str            mol_weight: float
hbond_donors: int           hbond_acceptors: int
rings: int                  aromatic_rings: int     stereocentres: int
functional_groups: list[str]        # keys from section 2, sorted
group_counts: dict[str, int]        # e.g. {"alcohol": 3}
hybridisation: dict[str, int]       # heavy atoms: {"sp": n, "sp2": n, "sp3": n}
```

## 4. Syllabus helpers (`syllabus.py`)
- `groups_for_grade(board, grade)` -> `{"in_syllabus": [...], "to_verify": [...]}`
- `relevant_groups(board, grade)` -> set of keys relevant at that grade
- `topics_for_group(board, grade, group)` -> chapters/topics that involve the group
- `practical_test_for_group(board, grade, group)` -> Class 12 practical test name or None
`covers_everything(board, grade)` -> bool. True for Classes 11 and 12: every detected group counts as
relevant there (many students also prepare for entrance exams), so do not skip a group because it is
missing from `relevant_groups()`. Class 10 is still gated by the chapter lists.
Use these to keep explanations at the right grade. `to_verify` entries come from NCERT knowledge, not
the PDFs, and are still being checked.

## 4b. PubChem data (`pubchem_data`, may be None)
```
{"cid": int|None, "iupac_name": str|None, "title": str|None, "smiles": str|None,
 "formula": str|None, "mol_weight": float|None, "xlogp": float|None, "tpsa": float|None}
```
Computed values from PubChem, not experimental measurements (no melting/boiling points yet).
Always handle `None` for the whole dict and for each field.

## 5. Explanation function (Person B implements, in `explain.py`)
```
generate_explanations(analysis: dict, pubchem_data: dict | None, board: str, grade: int) -> list[dict]
```
Each item:
```
{"property_id": str, "name": str, "value": str | None,
 "explanation": str | None, "has_more": bool}
```
Rules:
- Facts come only from `analysis` and `pubchem_data`. The model explains WHY; it never invents values.
- Only properties relevant to `grade` (use section 4).
- On failure return `[]` or items with `explanation: None`; do not raise (the API also guards this).
- `learn_more(property_id, analysis, board, grade) -> str` (planned, for the "find out more" button).

## 6. API (`main.py`)
`POST /api/analyze` (form data): `grade` (10/11/12, required), `board` (optional, defaults to "CBSE", the only
supported board, so the UI does not need a board selector), exactly one of `smiles`, `name`, `image`.
```
{"smiles", "source", "confidence", "iupac_name", "common_name", "formula", "board", "grade",
 "structure_svg": str | null,       # drawing of the structure the app understood
 "analysis": {...section 3...},
 "pubchem": {...section 4b...} | null,
 "relevant_groups": [...],          # detected groups to show for this grade
 "out_of_syllabus_groups": [...],   # only Class 10: detected groups beyond the syllabus (soft note)
 "properties": [...section 5...],
 "warnings": [str]}
```
`GET /api/config` -> `{"boards": ["CBSE"], "grades": [10, 11, 12], "image_input": bool}`
(`image_input` is false when the OCR service is not running: hide or disable the upload button.)
`GET /api/health` -> `{"status": "ok"}`

Errors: `{"error": str, "code": str}` with codes `INVALID_SMILES, INVALID_GRADE, INVALID_BOARD,
INVALID_INPUT, INVALID_REQUEST, NAME_NOT_FOUND (404), PUBCHEM_UNAVAILABLE (503),
LOOKUP_FAILED (502)`.
`source` is "smiles", "name" or "image". For "image", `confidence` is 0 to 1 (else null) and a warning is
added when it is low. The frontend should show `structure_svg` and `smiles` so the student can confirm
the image was read correctly and correct the SMILES if not.

Image errors: `INVALID_IMAGE (422)`, `IMAGE_TOO_LARGE (413, over 10 MB)`, `OCR_UNAVAILABLE (503)`,
`STRUCTURE_NOT_RECOGNISED (422)`. The last one may include `"smiles"` (what was read) so the UI can
offer it for editing.
