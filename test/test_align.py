import json
import numpy as np
import pytest
import synthetic
from align_scene import (align, detect_tag_scale, fit_floor, load_cameras, mat_to_quat, quat_mul, rot_between, rotate_sh1)
from gsplat_io import read_gs_ply
from utils import load_config

def _q2m(q):
    w, x, y, z = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)], [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)], [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

def test_rot_between_and_quat_roundtrip():
    rng = np.random.default_rng(1)
    for _ in range(20):
        a, b = rng.normal(size=3), rng.normal(size=3); a /= np.linalg.norm(a); b /= np.linalg.norm(b)
        R = rot_between(a, b)
        assert np.allclose(R @ a, b, atol=1e-9) and np.allclose(R.T @ R, np.eye(3), atol=1e-9)
        assert np.allclose(_q2m(mat_to_quat(R)), R, atol=1e-9)
    q1, q2 = mat_to_quat(rot_between(np.array([1., 0, 0]), np.array([0, 1., 0]))), mat_to_quat(rot_between(np.array([0, 1., 0]), np.array([0, 0, 1.])))
    assert np.allclose(_q2m(quat_mul(q1, q2[None])[0]), _q2m(q1) @ _q2m(q2), atol=1e-9)

def test_sh1_rotation_is_consistent():
    rng = np.random.default_rng(2); C1 = 0.4886025119029199
    rest = rng.normal(size=(5, 3, 3)); R = rot_between(np.array([0, 0, 1.]), np.array([0.3, 0.8, 0.5]) / np.linalg.norm([0.3, 0.8, 0.5]))
    new = rotate_sh1(rest, R)
    def f(r, d): return C1 * (-r[:, :, 0] * d[1] + r[:, :, 1] * d[2] - r[:, :, 2] * d[0])   # (y,z,x) order
    d = rng.normal(size=3); d /= np.linalg.norm(d)
    assert np.allclose(f(new, R @ d), f(rest, d), atol=1e-9)

def test_floor_fit_tilted():
    rng = np.random.default_rng(0); P, _ = synthetic.room_points(rng)
    R0 = synthetic._rotation(rng); X = P @ R0.T
    up = R0 @ np.array([0, 1.0, 0]) + 0.05 * rng.normal(size=3); up /= np.linalg.norm(up)
    n, d, inl = fit_floor(X, up, 0.3, 0.02)
    assert abs(n @ (R0 @ np.array([0, 1., 0]))) > 0.999 and inl > 0.4

def test_triangulate_tag_scale(tmp_path):
    info = synthetic.make(tmp_path)
    cams = load_cameras(tmp_path)
    tag = detect_tag_scale(cams, synthetic.TAG_M, "tag36h11")
    assert tag is not None and tag["tag_id"] == synthetic.TAG_ID
    assert abs(tag["scale"] - info["scale_true_m_per_unit"]) / info["scale_true_m_per_unit"] < 0.03

def test_align_with_tag(tmp_path):
    info = synthetic.make(tmp_path)
    t = align(load_cfg(), tmp_path)
    assert t["method"] == "apriltag" and not t["approximate"]
    d = read_gs_ply(tmp_path / "aligned.ply")
    fl = d["xyz"][np.abs(d["xyz"][:, 1]) < 0.1]
    assert len(fl) > 15000                                   # floor now at Y=0
    inside = d["xyz"][200:]
    xz = inside[:, [0, 2]] - inside[:, [0, 2]].mean(0)       # yaw is free: measure along the room's main axis
    ax = np.linalg.eigh(np.cov(xz.T))[1][:, -1]
    assert 5.8 < np.ptp(xz @ ax) < 6.2                       # 6 m long axis (metric)
    assert 2.4 < inside[:, 1].max() < 2.8                    # ceiling ~2.6 m, Y up
    cams = json.loads((tmp_path / "cameras_aligned.json").read_text())
    assert abs(np.median(np.array(cams["positions"])[:, 1]) - 1.5) < 0.08
    assert (tmp_path / "debug" / "floor_alignment.png").exists() and (tmp_path / "transform.json").exists()

def test_align_fallback_without_images(tmp_path):
    synthetic.make(tmp_path, with_images=False)
    t = align(load_cfg(), tmp_path)
    assert t["method"] == "camera_height_fallback" and t["approximate"]
    assert abs(t["median_camera_height_m"] - 1.4) < 0.05

def test_align_fallback_door_height(tmp_path):
    synthetic.make(tmp_path, with_images=False)
    cfg = load_cfg()
    cfg["align"]["fallback_scale_method"] = "door_height"
    cfg["align"]["fallback_door_height_m"] = 2.1
    t = align(cfg, tmp_path)
    assert t["method"] == "door_height_fallback" and t["approximate"]
    assert t["scale"] > 0

def load_cfg():
    return load_config("pipeline/config.yaml", "fast")

def test_ply_io_roundtrip_and_errors(tmp_path):
    from gsplat_io import write_gs_ply
    from utils import PipelineError
    rng = np.random.default_rng(3); n = 50
    d = {"xyz": rng.normal(size=(n, 3)), "dc": rng.normal(size=(n, 3)), "rest": rng.normal(size=(n, 3, 3)), "opacity": rng.normal(size=n),
         "scale": rng.normal(size=(n, 3)), "rot": np.tile([1.0, 0, 0, 0], (n, 1))}
    write_gs_ply(tmp_path / "a.ply", d, 1); r = read_gs_ply(tmp_path / "a.ply")
    assert np.allclose(r["xyz"], d["xyz"], atol=1e-6) and np.allclose(r["rest"], d["rest"], atol=1e-6) and r["rest"].shape == (n, 3, 3)
    (tmp_path / "bad.ply").write_bytes(b"ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nend_header\n1\n")
    with pytest.raises(PipelineError): read_gs_ply(tmp_path / "bad.ply")
    (tmp_path / "trunc.ply").write_bytes((tmp_path / "a.ply").read_bytes()[:-100])
    with pytest.raises(PipelineError): read_gs_ply(tmp_path / "trunc.ply")
