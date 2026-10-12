import json
from pathlib import Path
import pytest
import synthetic
from run_pipeline import main
from report import build_report

def _cfg(tmp):
    c = tmp / "cfg.yaml"; c.write_text(open("pipeline/config.yaml").read().replace("viewer_scene_dir: null", f"viewer_scene_dir: {tmp / 'vs'}")); return c

def _prep(tmp):
    out = tmp / "out"; synthetic.make(out)
    (out / ".markers").mkdir(exist_ok=True)
    for s in ("extract_frames", "reconstruct"): (out / ".markers" / f"{s}.done").write_text("ok")
    (out / "timings.json").write_text(json.dumps({"extract_frames": {"seconds": 1.5, "frames_kept": 60}, "reconstruct": {"seconds": 100.0}}))
    (out / "frames_report.json").write_text(json.dumps({"kept": 60, "candidates": 90, "dropped_blur": 20, "dropped_duplicate": 10, "avg_sharpness": 123.4, "target_count": 200}))
    (out / "reconstruct_report.json").write_text(json.dumps({"images_input": 60, "images_registered": 57, "registration_rate": 0.95, "gaussian_count": 53500, "iterations": 7000, "metrics": {}}))
    v = tmp / "v.mp4"; v.write_bytes(b"x"); return out, v

def test_report_written_with_real_values_only(tmp_path):
    out, v = _prep(tmp_path)
    assert main(["--video", str(v), "--out", str(out), "--resume", "--config", str(_cfg(tmp_path))]) == 0
    r = json.loads((out / "report.json").read_text())
    assert r["status"] == "ok" and set(r["stage_seconds"]) == {"extract_frames", "reconstruct", "align_scene", "build_collision", "export_scene"}
    assert r["total_stage_seconds"] == pytest.approx(sum(r["stage_seconds"].values()), abs=0.2)
    assert r["frames"]["kept"] == 60 and r["reconstruction"]["registration_rate"] == 0.95
    assert r["alignment"]["scale_method"] == "apriltag" and r["export"]["gaussians_after"] > 0 and r["export"]["size_mb_after"] > 0
    md = (out / "report.md").read_text()
    assert "Registration rate | 95.0%" in md and "apriltag" in md and "| align_scene |" in md

def test_failed_stage_gives_failed_report_and_resume_hint(tmp_path, caplog):
    out, v = _prep(tmp_path)
    (out / "splat.ply").unlink()                                   # align_scene cannot run
    caplog.set_level("ERROR", logger="roomscape")
    assert main(["--video", str(v), "--out", str(out), "--resume", "--config", str(_cfg(tmp_path))]) == 2
    r = json.loads((out / "report.json").read_text())
    assert r["status"] == "failed" and r["failed_stage"] == "align_scene"
    assert any("--resume" in m.message for m in caplog.records)

def test_missing_data_is_null_not_invented(tmp_path):
    r = build_report(tmp_path, "fast", 1.0)
    assert r["frames"]["kept"] is None and r["reconstruction"]["gaussian_count"] is None and r["alignment"]["scale_method"] is None
    from report import render_md
    assert "n/a" in render_md(r)

SAMPLE = Path("test/sample_video")
@pytest.mark.skipif(not any(SAMPLE.glob("*.mp4")) and not any(SAMPLE.glob("*.mov")), reason="no real sample video in test/sample_video (needs GPU + Nerfstudio too)")
def test_full_pipeline_on_real_sample(tmp_path):
    import shutil
    if not (shutil.which("ns-train") and shutil.which("colmap")): pytest.skip("Nerfstudio/COLMAP not installed")
    assert main(["--video", str(SAMPLE), "--out", str(tmp_path / "out"), "--mode", "fast"]) == 0
    assert json.loads((tmp_path / "out" / "report.json").read_text())["reconstruction"]["registration_rate"] > 0.5
