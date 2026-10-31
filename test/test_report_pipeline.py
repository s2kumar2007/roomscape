import json
from pathlib import Path
import pytest
import synthetic
from run_pipeline import main
from report import build_report, render_md

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
    assert not md.startswith("**MOCK RUN")

def test_failed_stage_gives_failed_report_and_resume_hint(tmp_path, caplog):
    out, v = _prep(tmp_path)
    (out / "splat.ply").unlink()                                   # align_scene cannot run
    caplog.set_level("ERROR", logger="roomscape")
    assert main(["--video", str(v), "--out", str(out), "--resume", "--config", str(_cfg(tmp_path))]) == 2
    r = json.loads((out / "report.json").read_text())
    assert r["status"] == "failed" and r["failed_stage"] == "align_scene"
    assert r.get("failure_reason") is not None and "splat.ply" in r["failure_reason"]
    md = (out / "report.md").read_text()
    assert "Failure reason" in md and "splat.ply" in md
    assert any("--resume" in m.message for m in caplog.records)

def test_mock_pipeline_runs_end_to_end_on_cpu(synth_video, tmp_path):
    out = tmp_path / "mock_out"
    cfg_file = _cfg(tmp_path)
    ret = main([
        "--video", str(synth_video),
        "--out", str(out),
        "--config", str(cfg_file),
        "--mock",
        "--frames", "25",
    ])
    assert ret == 0
    r = json.loads((out / "report.json").read_text())

    # (c) Refuse to produce final report as status "ok" in mock mode: use status "mock"
    assert r["status"] == "mock"
    # (a) When --mock/--dry-run is used, put "mock": true in report.json
    assert r["mock"] is True

    assert set(r["stage_seconds"]) == {"extract_frames", "reconstruct", "align_scene", "build_collision", "export_scene"}
    assert r["frames"]["kept"] > 0
    assert r["reconstruction"]["registration_rate"] == 1.0
    assert r["reconstruction"]["gaussian_count"] > 0
    assert (out / "debug" / "floor_alignment.png").exists()
    assert (out / "occupancy.png").exists()

    # (a) "mock": true in timings.json and scene meta.json
    timings = json.loads((out / "timings.json").read_text())
    assert timings.get("mock") is True
    meta = json.loads((out / "scene" / "meta.json").read_text())
    assert meta.get("mock") is True
    scene_info = json.loads((out / "scene_info.json").read_text())
    assert scene_info.get("mock") is True

    # (a) bold "MOCK RUN - NOT A REAL RECONSTRUCTION" line at the top of report.md
    md = (out / "report.md").read_text()
    assert md.startswith("**MOCK RUN - NOT A REAL RECONSTRUCTION**")

    # (b) In mock mode do NOT copy anything into viewer/public/scene/; write to out/ only
    vs = tmp_path / "vs"
    assert not vs.exists() or len(list(vs.iterdir())) == 0

def test_report_refuses_ok_status_in_mock_mode(tmp_path):
    # Test refusal when mock=True argument is explicitly passed
    r = build_report(tmp_path, "fast", 1.0, status="ok", mock=True)
    assert r["status"] == "mock"
    assert r["mock"] is True
    md = render_md(r)
    assert md.startswith("**MOCK RUN - NOT A REAL RECONSTRUCTION**")

    # Test refusal when timings.json indicates a mock run
    (tmp_path / "timings.json").write_text(json.dumps({"mock": True}))
    r2 = build_report(tmp_path, "fast", 1.0, status="ok")
    assert r2["status"] == "mock"
    assert r2["mock"] is True

    # Test refusal when meta.json indicates a mock run
    (tmp_path / "scene").mkdir(exist_ok=True)
    (tmp_path / "scene" / "meta.json").write_text(json.dumps({"mock": True}))
    r3 = build_report(tmp_path, "fast", 1.0, status="ok")
    assert r3["status"] == "mock"
    assert r3["mock"] is True

def test_mock_mode_does_not_copy_to_viewer_public_scene(synth_video, tmp_path):
    out = tmp_path / "out_mock_default_dir"
    # Create a dummy config without overriding viewer_scene_dir (defaults to viewer/public/scene)
    cfg_file = tmp_path / "default_cfg.yaml"
    cfg_file.write_text(open("pipeline/config.yaml").read())
    ret = main([
        "--video", str(synth_video),
        "--out", str(out),
        "--config", str(cfg_file),
        "--mock",
        "--frames", "10",
    ])
    assert ret == 0
    # Output scene files exist in out/
    assert (out / "scene" / "meta.json").exists()
    assert (out / "scene" / "scene.splat").exists() or (out / "scene" / "scene.ply").exists()
    # But export report confirms viewer copy was skipped in mock mode
    exp_report = json.loads((out / "export_report.json").read_text())
    assert exp_report.get("viewer_dir") is None
    assert exp_report.get("mock") is True

def test_missing_data_is_null_not_invented(tmp_path):
    r = build_report(tmp_path, "fast", 1.0)
    assert r["frames"]["kept"] is None and r["reconstruction"]["gaussian_count"] is None and r["alignment"]["scale_method"] is None
    from report import render_md
    assert "n/a" in render_md(r)

def test_cli_flags_frames_trim_no_gpu(tmp_path):
    out, v = _prep(tmp_path)
    cfg_file = _cfg(tmp_path)
    ret = main([
        "--video", str(v),
        "--out", str(out),
        "--resume",
        "--config", str(cfg_file),
        "--frames", "150",
        "--trim-start", "1.2",
        "--trim-end", "5.8",
        "--no-gpu",
    ])
    assert ret == 0

def test_colab_notebook_structure():
    nb_path = Path("notebooks/colab_reconstruct.ipynb")
    assert nb_path.exists()
    nb = json.loads(nb_path.read_text())
    assert "cells" in nb
    all_code = "\n".join("".join(c["source"]) for c in nb["cells"] if c.get("cell_type") == "code")
    assert "FRAMES" in all_code
    assert "TRIM_START" in all_code
    assert "TRIM_END" in all_code
    assert "use_gpu" in all_code and "False" in all_code.replace("false", "False")
    assert "run_pipeline.py" in all_code
    # Ensure no `if ...: !cmd` one-liners in any cell
    for c in nb["cells"]:
        if c.get("cell_type") == "code":
            for line in c["source"]:
                stripped = line.strip()
                if stripped.startswith("if ") and ": !" in stripped:
                    pytest.fail(f"Invalid IPython one-liner detected: {line}")

SAMPLE = Path("test/sample_video")
@pytest.mark.skipif(not any(SAMPLE.glob("*.mp4")) and not any(SAMPLE.glob("*.mov")), reason="no real sample video in test/sample_video (needs GPU + Nerfstudio too)")
def test_full_pipeline_on_real_sample(tmp_path):
    import shutil
    if not (shutil.which("ns-train") and shutil.which("colmap")): pytest.skip("Nerfstudio/COLMAP not installed")
    assert main(["--video", str(SAMPLE), "--out", str(tmp_path / "out"), "--mode", "fast"]) == 0
    assert json.loads((tmp_path / "out" / "report.json").read_text())["reconstruction"]["registration_rate"] > 0.5
