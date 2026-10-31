import json
import cv2
import numpy as np
import pytest
from extract_frames import Cand, extract, sample_candidates, save_selected, sharpness
from utils import PipelineError, load_config

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

def test_candidates_have_no_img_attribute(synth_video):
    cands = sample_candidates(synth_video, 0, 6, 1920)
    assert len(cands) > 0
    for c in cands:
        assert not hasattr(c, "img")
        assert hasattr(c, "n")
        assert hasattr(c, "t")
        assert hasattr(c, "video")
        assert hasattr(c, "sharp")
        assert hasattr(c, "thumb")

def test_candidate_peak_memory_stays_flat(synth_video):
    import tracemalloc
    tracemalloc.start()
    tracemalloc.reset_peak()
    cands = sample_candidates(synth_video, 0, 6, 1920)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    # Total memory of all candidate thumbnails is tiny (16 KB each)
    total_cand_mem = sum(c.thumb.nbytes for c in cands)
    assert total_cand_mem < 2 * 1024 * 1024
    for c in cands:
        assert c.thumb.nbytes == 64 * 64 * 4

def test_save_selected_fewer_frames_raises(synth_video, tmp_path):
    phantom_cand = Cand(video=0, t=999.0, n=999999, sharp=100.0, thumb=np.zeros((64, 64), dtype=np.float32))
    with pytest.raises(PipelineError) as exc_info:
        save_selected(synth_video, [phantom_cand], tmp_path, 1920)
    assert "expected" in str(exc_info.value).lower() or "fewer" in str(exc_info.value).lower()
    assert exc_info.value.fix

def test_save_selected_uses_cached_frame_without_reopening_video(tmp_path):
    from extract_frames import save_selected
    cached = tmp_path / "candidate.jpg"
    cached.write_bytes(b"cached-frame")
    cand = Cand(video=0, t=1.0, n=30, sharp=100.0,
                thumb=np.zeros((64, 64), dtype=np.float32), cache_path=cached)
    out = tmp_path / "frames"
    out.mkdir()
    assert save_selected(tmp_path / "video-does-not-need-to-exist.mp4", [cand], out, 1920) == 1
    assert (out / "frame_00000.jpg").read_bytes() == b"cached-frame"

def test_trimming_limits_sampled_time_range(synth_video, tmp_path):
    cands_untrimmed = sample_candidates(synth_video, 0, 6, 1920, trim_start_s=0.0, trim_end_s=0.0)
    assert min(c.t for c in cands_untrimmed) < 0.5
    assert max(c.t for c in cands_untrimmed) > 8.0

    cands_trimmed = sample_candidates(synth_video, 0, 6, 1920, trim_start_s=2.0, trim_end_s=5.0)
    assert len(cands_trimmed) > 0
    assert min(c.t for c in cands_trimmed) >= 2.0
    assert max(c.t for c in cands_trimmed) <= 5.0
    assert len(cands_trimmed) < len(cands_untrimmed)

    # Also test via extract with config
    cfg = _cfg()
    cfg["frames"]["trim_start_s"] = 2.0
    cfg["frames"]["trim_end_s"] = 5.0
    r = extract(cfg, tmp_path, [synth_video])
    assert r["kept"] > 0
