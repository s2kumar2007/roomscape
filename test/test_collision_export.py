import json, sys
import numpy as np
import pytest
import synthetic
from align_scene import align
from build_collision import BLOCKED, FLOOR, UNKNOWN, build, rle_decode, rle_encode
from export_scene import export, read_splat
from gsplat_io import read_gs_ply
from run_pipeline import main
from utils import load_config

def cfg(tmp):
    c = load_config("pipeline/config.yaml", "fast"); c["export"]["viewer_scene_dir"] = str(tmp / "viewer_scene"); return c

@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    out = tmp_path_factory.mktemp("scene"); synthetic.make(out); c = cfg(out); align(c, out); build(c, out); return out, c

def test_rle_roundtrip():
    a = np.random.default_rng(0).integers(0, 3, (17, 23)).astype(np.uint8)
    assert (rle_decode(rle_encode(a), a.shape) == a).all()

def test_collision_grid_semantics(scene):
    out, c = scene
    doc = json.loads((out / "collision.json").read_text()); nx, nz = doc["size"]
    g = rle_decode(doc["grid"], (nz, nx)); inf = rle_decode(doc["inflated"], (nz, nx))
    assert doc["floor_height"] == 0 and doc["encoding"] == "rle_row_major"
    assert (g == FLOOR).sum() > 0.5 * (g != UNKNOWN).sum()                 # mostly walkable room interior
    assert (g == BLOCKED).sum() > 0                                         # walls + table exist
    assert (inf == FLOOR).sum() < (g == FLOOR).sum()                        # inflation removes cells near obstacles
    assert ((inf == BLOCKED) | (g != BLOCKED)).all()                        # inflated is superset of blocked
    area = (g == FLOOR).sum() * doc["cell_size"] ** 2
    assert 14 < area < 26                                                   # 6x4 m room minus table, minus wall zones
    assert (out / "occupancy.png").exists()

def test_table_is_blocked_floor_free(scene):
    out, _ = scene
    doc = json.loads((out / "collision.json").read_text()); nx, nz = doc["size"]
    g = rle_decode(doc["grid"], (nz, nx)); ox, oz = doc["origin"]; cell = doc["cell_size"]
    d = read_gs_ply(out / "aligned.ply")
    # table top points (y~0.75, inside blocked band) -> their cells must be BLOCKED
    top = d["xyz"][(np.abs(d["xyz"][:, 1] - 0.75) < 0.03) & (np.arange(len(d["xyz"])) > 200)]
    ix = ((top[:, 0] - ox) / cell).astype(int).clip(0, nx - 1); iz = ((top[:, 2] - oz) / cell).astype(int).clip(0, nz - 1)
    assert (g[iz, ix] == BLOCKED).mean() > 0.9

def test_export_formats_and_meta(scene):
    out, c = scene
    for fmt in ("splat", "ply", "bogus"):
        rep = export(c, out, fmt)
        assert rep["gaussians_after"] < rep["gaussians_before"]            # floaters pruned
        assert rep["size_mb_after"] <= c["export"]["max_size_mb"]
    meta = json.loads((out / "scene" / "meta.json").read_text())
    assert meta["format"] == "splat" and meta["scale"]["method"] == "apriltag"   # 'bogus' fell back to splat
    assert abs(meta["spawn"]["position"][1] - 1.6) < 1e-6 and -3.15 <= meta["spawn"]["yaw"] <= 3.15
    dest = out / "viewer_scene"; assert (dest / "scene.splat").exists() and (dest / "collision.json").exists() and (dest / "meta.json").exists()
    assert not (dest / "scene.ply").exists()
    s = read_splat(dest / "scene.splat"); assert len(s["xyz"]) == meta["gaussian_count"]
    assert (dest / "scene.splat").stat().st_size == 32 * meta["gaussian_count"]

def test_spawn_is_walkable(scene):
    out, c = scene; export(c, out, "splat")
    meta = json.loads((out / "scene" / "meta.json").read_text()); doc = json.loads((out / "collision.json").read_text())
    nx, nz = doc["size"]; inf = rle_decode(doc["inflated"], (nz, nx)); x, _, z = meta["spawn"]["position"]
    assert inf[int((z - doc["origin"][1]) / doc["cell_size"]), int((x - doc["origin"][0]) / doc["cell_size"])] == FLOOR

def test_pipeline_end_to_end_from_aligned_stages(tmp_path):
    """Run the real CLI over stages 3-5 using markers to skip GPU stages (frames/reconstruct done on synthetic data)."""
    out = tmp_path / "out"; synthetic.make(out)
    for s in ("extract_frames", "reconstruct"): (out / ".markers").mkdir(exist_ok=True); (out / ".markers" / f"{s}.done").write_text("ok")
    vid = tmp_path / "v.mp4"; vid.write_bytes(b"x")
    c = tmp_path / "cfg.yaml"; base = open("pipeline/config.yaml").read()
    c.write_text(base.replace("viewer_scene_dir: null", f"viewer_scene_dir: {tmp_path / 'vs'}"))
    assert main(["--video", str(vid), "--out", str(out), "--resume", "--config", str(c), "--format", "splat"]) == 0
    t = json.loads((out / "timings.json").read_text())
    assert {"align_scene", "build_collision", "export_scene"} <= set(t)
    assert (tmp_path / "vs" / "scene.splat").exists()
