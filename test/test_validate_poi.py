"""test_validate_poi.py: Pytest suite for scripts/validate_poi.py."""
import json
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from validate_poi import validate_poi

def test_valid_poi_file(tmp_path):
    col_path = REPO_ROOT / "viewer" / "public" / "scene" / "collision.json"
    demo_poi = REPO_ROOT / "viewer" / "public" / "scene" / "poi.json"
    ok, errors = validate_poi(demo_poi, col_path)
    assert ok is True
    assert len(errors) == 0

def test_invalid_duplicate_id_and_out_of_bounds(tmp_path):
    col_path = REPO_ROOT / "viewer" / "public" / "scene" / "collision.json"
    poi_data = {
        "version": 1,
        "pois": [
            {"id": "p1", "name": "Point 1", "category": "door", "position": [0.65, -4.25]},
            {"id": "p1", "name": "Point 1 Duplicate", "category": "door", "position": [1.5, -3.5]},
            {"id": "p2", "name": "Out of Bounds", "category": "door", "position": [999.0, 999.0]},
            {"id": "p3", "name": "Invalid Position", "category": "door", "position": ["bad", "coords"]},
        ],
    }
    p_file = tmp_path / "poi.json"
    p_file.write_text(json.dumps(poi_data))

    ok, errors = validate_poi(p_file, col_path)
    assert ok is False
    assert any("Duplicate ID" in e for e in errors)
    assert any("outside scene bounds" in e for e in errors)
    assert any("coordinates must be numbers" in e for e in errors)

def test_invalid_version_or_format(tmp_path):
    col_path = REPO_ROOT / "viewer" / "public" / "scene" / "collision.json"
    p_file = tmp_path / "poi.json"
    p_file.write_text(json.dumps({"version": 2, "pois": "not a list"}))

    ok, errors = validate_poi(p_file, col_path)
    assert ok is False
    assert any("version 1" in e for e in errors)
    assert any("'pois' field must be a list" in e for e in errors)
