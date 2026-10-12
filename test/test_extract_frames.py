import json
import cv2
from extract_frames import extract, sharpness
from utils import load_config

def _cfg(n=40):
    c = load_config("pipeline/config.yaml", "fast")
    c["frames"]["target_count"] = n
    return c

def test_extract_drops_blur_and_duplicates(synth_video, tmp_path):
    r = extract(_cfg(), tmp_path, [synth_video])
    assert r["dropped_blur"] > 0
    assert r["dropped_duplicate"] > 0
    assert 0 < r["kept"] <= 40
    assert len(list((tmp_path / "frames").glob("*.jpg"))) == r["kept"]
    assert json.loads((tmp_path / "frames_report.json").read_text())["kept"] == r["kept"]

def test_kept_frames_are_sharp(synth_video, tmp_path):
    extract(_cfg(), tmp_path, [synth_video])
    vals = [sharpness(cv2.cvtColor(cv2.imread(str(f)), cv2.COLOR_BGR2GRAY)) for f in (tmp_path / "frames").glob("*.jpg")]
    assert min(vals) > 30.0

def test_target_cap_and_multi_video(synth_video, tmp_path):
    r = extract(_cfg(20), tmp_path, [synth_video, synth_video])
    assert r["kept"] <= 22  # proportional split may round up by 1 per video
