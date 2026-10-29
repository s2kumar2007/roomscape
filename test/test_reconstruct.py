"""Orchestration tests using FAKE ns-* executables (no GPU needed). Real COLMAP/training is verified on a GPU machine."""
import json, os, stat, sys
import pytest
from reconstruct import (check_registration, ply_vertex_count, reconstruct, registration_stats, run_cmd)
from utils import PipelineError, load_config

FAKE = {
"ns-process-data": '''#!/usr/bin/env python3
import sys, json, pathlib
a=sys.argv; out=pathlib.Path(a[a.index("--output-dir")+1]); out.mkdir(parents=True, exist_ok=True)
n=len(list(pathlib.Path(a[a.index("--data")+1]).glob("*.jpg"))); k=int(n*FRAC)
(out/"transforms.json").write_text(json.dumps({"frames":[{"file_path":f"{i}.jpg"} for i in range(k)]}))
(out/"used_no_gpu.txt").write_text("yes" if "--no-gpu" in a else "no")
print("fake colmap done", "no-gpu" if "--no-gpu" in a else "gpu")''',
"ns-train": '''#!/usr/bin/env python3
import sys, pathlib
a=sys.argv; o=pathlib.Path(a[a.index("--output-dir")+1])/"scene"/"splatfacto"/"run"; o.mkdir(parents=True, exist_ok=True)
(o/"config.yml").write_text("x"); print("fake train", a[a.index("--max-num-iterations")+1])''',
"ns-export": '''#!/usr/bin/env python3
import sys, pathlib
a=sys.argv; o=pathlib.Path(a[a.index("--output-dir")+1]); o.mkdir(parents=True, exist_ok=True)
(o/"splat.ply").write_text("ply\\nformat ascii 1.0\\nelement vertex 1234\\nproperty float x\\nend_header\\n")''',
"colmap": "#!/bin/sh\necho colmap", "ffmpeg": "#!/bin/sh\necho ffmpeg", "nvidia-smi": "#!/bin/sh\necho gpu"}

@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    monkeypatch.setattr("reconstruct.check_gpu", lambda: {
        "cuda_available": True, "device_name": "Fake CUDA", "vram_total_gb": 8.0,
        "vram_free_gb": 7.0, "diagnostic": None,
    })
    def make(frac):
        b = tmp_path / "bin"; b.mkdir(exist_ok=True)
        for n, body in FAKE.items():
            f = b / n; f.write_text(body.replace("FRAC", str(frac))); f.chmod(f.stat().st_mode | stat.S_IEXEC)
            if sys.platform == "win32":
                if body.startswith("#!/usr/bin/env python3"):
                    (b / f"{n}.cmd").write_text(f'@"{sys.executable}" "{f}" %*\n')
                else:
                    (b / f"{n}.cmd").write_text(f'@echo {n}\n')
        monkeypatch.setenv("PATH", str(b) + os.pathsep + os.environ["PATH"])
        out = tmp_path / "out"; (out / "frames").mkdir(parents=True, exist_ok=True)
        for i in range(100): (out / "frames" / f"frame_{i:05d}.jpg").write_bytes(b"x")
        return out
    return make

def test_full_stage_with_fakes(fake_env):
    out = fake_env(0.95)
    rep = reconstruct(load_config("pipeline/config.yaml", "fast"), out)
    assert rep["registration_rate"] == 0.95 and rep["gaussian_count"] == 1234
    assert (out / "splat.ply").exists() and (out / "reconstruct_report.json").exists()

def test_low_registration_warns_not_fails(fake_env, caplog):
    out = fake_env(0.5)
    caplog.set_level("WARNING", logger="roomscape")
    reconstruct(load_config("pipeline/config.yaml", "fast"), out)
    assert any("registered" in r.message for r in caplog.records)

def test_too_few_registered_raises(fake_env):
    out = fake_env(0.1)
    with pytest.raises(PipelineError) as e:
        reconstruct(load_config("pipeline/config.yaml", "fast"), out)
    assert "Re-capture" in e.value.fix

def test_failed_subprocess_raises_with_fix(tmp_path):
    with pytest.raises(PipelineError) as e:
        cmd = [sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"]
        run_cmd(cmd, tmp_path / "x.log", "try this")
    assert "exit 3" in str(e.value) and e.value.fix == "try this"

def test_missing_tool_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(PipelineError) as e:
        reconstruct(load_config("pipeline/config.yaml", "fast"), tmp_path)
    assert "ns-train" in str(e.value)

def test_ply_count_and_stats(tmp_path):
    p = tmp_path / "a.ply"; p.write_text("ply\nelement vertex 77\nend_header\n")
    assert ply_vertex_count(p) == 77
    (tmp_path / "transforms.json").write_text(json.dumps({"frames": [1, 2, 3]}))
    assert registration_stats(tmp_path, 4)["registration_rate"] == 0.75

def test_colmap_use_gpu_default_true(fake_env):
    out = fake_env(0.95)
    cfg = load_config("pipeline/config.yaml", "fast")
    assert cfg["colmap"].get("use_gpu") is True
    reconstruct(cfg, out)
    assert (out / "ns_data" / "used_no_gpu.txt").read_text() == "no"
    assert "fake colmap done gpu" in (out / "logs" / "colmap.log").read_text()

def test_colmap_use_gpu_false_passes_no_gpu(fake_env):
    out = fake_env(0.95)
    cfg = load_config("pipeline/config.yaml", "fast")
    cfg["colmap"]["use_gpu"] = False
    reconstruct(cfg, out)
    assert (out / "ns_data" / "used_no_gpu.txt").read_text() == "yes"
    assert "fake colmap done no-gpu" in (out / "logs" / "colmap.log").read_text()

def test_check_gpu():
    from reconstruct import check_gpu
    info = check_gpu()
    assert isinstance(info, dict)
    assert "cuda_available" in info
    assert "device_name" in info
    assert "vram_total_gb" in info

def test_validate_environment(monkeypatch, tmp_path):
    from reconstruct import validate_environment
    # Mock mode should always succeed without checking binaries
    mock_res = validate_environment(mock=True)
    assert mock_res["mock"] is True
    assert mock_res["tools_ok"] is True
    # Non-mock mode with empty PATH should fail with actionable message
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(PipelineError) as exc_info:
        validate_environment(mock=False)
    assert "Missing required tools in PATH" in str(exc_info.value)
    assert exc_info.value.fix != ""

def test_real_training_requires_cuda():
    from reconstruct import require_training_gpu
    with pytest.raises(PipelineError, match="Cannot start Nerfstudio training") as exc_info:
        require_training_gpu({"cuda_available": False, "diagnostic": None})
    assert "--mock/--dry-run" in exc_info.value.fix

def test_mock_reconstruct_on_cpu(tmp_path):
    out = tmp_path / "out"
    frames = out / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    for i in range(25):
        (frames / f"frame_{i:05d}.jpg").write_bytes(b"dummy")

    cfg = load_config("pipeline/config.yaml", "fast")
    cfg["_mock"] = True
    rep = reconstruct(cfg, out)
    assert rep["registration_rate"] == 1.0
    assert rep["images_registered"] == 25
    assert rep["gaussian_count"] > 1000
    assert (out / "splat.ply").exists()
    assert (out / "ns_data" / "transforms.json").exists()
    assert (out / "reconstruct_report.json").exists()

def test_subprocess_stderr_logged_to_console(tmp_path, caplog):
    caplog.set_level("ERROR", logger="roomscape")
    cmd = [sys.executable, "-c", "import sys; sys.stderr.write('fatal cuda error\\n'); sys.exit(2)"]
    with pytest.raises(PipelineError) as exc_info:
        run_cmd(cmd, tmp_path / "err.log", "check your drivers")
    assert "exit 2" in str(exc_info.value)
    assert "fatal cuda error" in str(exc_info.value)
    assert exc_info.value.fix == "check your drivers"
    assert any("fatal cuda error" in r.message for r in caplog.records)
