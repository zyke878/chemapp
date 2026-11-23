"""Run with:  pytest -v   (from the backend/ folder)"""
import syllabus
from chem import GROUP_KEYS


def test_supported_values():
    assert syllabus.SUPPORTED_BOARDS == ["CBSE"]
    assert syllabus.SUPPORTED_GRADES == [10, 11, 12]


def test_every_group_key_in_syllabus_exists_in_engine():
    for grade in syllabus.SUPPORTED_GRADES:
        for ch in syllabus.chapters("CBSE", grade):
            for key in ch.get("groups_in_syllabus", []) + ch.get("groups_to_verify", []):
                assert key in GROUP_KEYS, f"Unknown group '{key}' in Class {grade}: {ch['name']}"


def test_every_engine_group_is_taught_somewhere():
    used = set()
    for grade in syllabus.SUPPORTED_GRADES:
        used |= syllabus.relevant_groups("CBSE", grade)
    assert set(GROUP_KEYS) - used == set(), "Groups detected by the engine but not in any grade"


def test_class_10_scope():
    g = syllabus.groups_for_grade("CBSE", 10)
    assert {"alkane", "alkene", "alkyne", "haloalkane", "alcohol",
            "aldehyde", "ketone", "carboxylic_acid"} <= set(g["in_syllabus"])
    assert "phenol" not in syllabus.relevant_groups("CBSE", 10)
    assert "primary_amine" not in syllabus.relevant_groups("CBSE", 10)


def test_class_12_scope():
    rel = syllabus.relevant_groups("CBSE", 12)
    assert {"phenol", "ether", "primary_amine", "diazonium_salt", "carbohydrate", "amino_acid"} <= rel


def test_no_group_listed_as_both_verified_and_to_verify():
    for grade in syllabus.SUPPORTED_GRADES:
        g = syllabus.groups_for_grade("CBSE", grade)
        assert not set(g["in_syllabus"]) & set(g["to_verify"])


def test_practical_tests_class_12():
    assert syllabus.practical_test_for_group("CBSE", 12, "alcohol") == "alcoholic group"
    assert syllabus.practical_test_for_group("CBSE", 10, "alcohol") is None


def test_topics_for_group():
    out = syllabus.topics_for_group("CBSE", 12, "diazonium_salt")
    assert out and out[0]["chapter"] == "Amines"


def test_covers_everything_flags():
    assert syllabus.covers_everything("CBSE", 10) is False
    assert syllabus.covers_everything("CBSE", 11) is True
    assert syllabus.covers_everything("CBSE", 12) is True
