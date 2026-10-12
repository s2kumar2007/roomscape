"""Phase 4: align the splat to a metric, floor-aligned, Y-up frame (floor at Y=0).

1. Floor: vectorised RANSAC plane fit on the lowest part of the scene (along mean camera-up), normal
   constrained near camera-up. Rotate normal -> +Y, translate floor -> Y=0.
2. Scale: (a) triangulate an AprilTag/ArUco marker of known size from the camera rays -> metres per unit;
   (b) fallback: median camera height := fallback height (approximate, flagged).
3. Apply similarity to positions, rotations (quaternions), scales (log) and SH degree-1 coefficients
   (higher SH bands are dropped: rotating them needs Wigner matrices; documented trade-off).
Nerfstudio trains in a dataparser-transformed frame; camera poses are mapped into it via
dataparser_transforms.json before use.
"""
from __future__ import annotations
import json
from pathlib import Path
import cv2
import numpy as np
from gsplat_io import read_gs_ply, write_gs_ply
from utils import PipelineError, get_logger

log = get_logger()
TAG_DICTS = {"tag36h11": "DICT_APRILTAG_36h11", "tag25h9": "DICT_APRILTAG_25h9", "tag16h5": "DICT_APRILTAG_16h5",
             "tag36h10": "DICT_APRILTAG_36h10"}

# ---------- math helpers ----------
def quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product (wxyz). a: (4,) or (N,4); b: (N,4)."""
    a = np.broadcast_to(a, b.shape)
    return np.stack([a[:, 0]*b[:, 0] - a[:, 1]*b[:, 1] - a[:, 2]*b[:, 2] - a[:, 3]*b[:, 3],
                     a[:, 0]*b[:, 1] + a[:, 1]*b[:, 0] + a[:, 2]*b[:, 3] - a[:, 3]*b[:, 2],
                     a[:, 0]*b[:, 2] - a[:, 1]*b[:, 3] + a[:, 2]*b[:, 0] + a[:, 3]*b[:, 1],
                     a[:, 0]*b[:, 3] + a[:, 1]*b[:, 2] - a[:, 2]*b[:, 1] + a[:, 3]*b[:, 0]], 1)

def mat_to_quat(R: np.ndarray) -> np.ndarray:
    t = np.trace(R)
    if t > 0:
        s = np.sqrt(t + 1) * 2; q = [s / 4, (R[2, 1]-R[1, 2]) / s, (R[0, 2]-R[2, 0]) / s, (R[1, 0]-R[0, 1]) / s]
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = np.sqrt(1 + R[0, 0] - R[1, 1] - R[2, 2]) * 2; q = [(R[2, 1]-R[1, 2]) / s, s / 4, (R[0, 1]+R[1, 0]) / s, (R[0, 2]+R[2, 0]) / s]
    elif R[1, 1] > R[2, 2]:
        s = np.sqrt(1 + R[1, 1] - R[0, 0] - R[2, 2]) * 2; q = [(R[0, 2]-R[2, 0]) / s, (R[0, 1]+R[1, 0]) / s, s / 4, (R[1, 2]+R[2, 1]) / s]
    else:
        s = np.sqrt(1 + R[2, 2] - R[0, 0] - R[1, 1]) * 2; q = [(R[1, 0]-R[0, 1]) / s, (R[0, 2]+R[2, 0]) / s, (R[1, 2]+R[2, 1]) / s, s / 4]
    q = np.array(q); return q / np.linalg.norm(q)

def rot_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Rotation matrix taking unit vector a to unit vector b."""
    v = np.cross(a, b); c = float(a @ b)
    if c < -0.999999:
        ax = np.cross(a, [1, 0, 0]); ax = ax if np.linalg.norm(ax) > 1e-6 else np.cross(a, [0, 1, 0]); ax /= np.linalg.norm(ax)
        return 2 * np.outer(ax, ax) - np.eye(3)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K / (1 + c)

def rotate_sh1(rest: np.ndarray, R: np.ndarray) -> np.ndarray:
    """Rotate degree-1 SH coefficients (stored order y,z,x with the 3DGS sign convention)."""
    out = rest[:, :, :3].copy()
    V = np.stack([-out[:, :, 2], -out[:, :, 0], out[:, :, 1]], -1) @ R.T   # (N,3ch,3xyz)
    out[:, :, 0], out[:, :, 1], out[:, :, 2] = -V[..., 1], V[..., 2], -V[..., 0]
    return out

# ---------- cameras ----------
def load_cameras(out: Path) -> dict:
    """Camera centres/rotations in the SPLAT frame (dataparser transform applied) + intrinsics."""
    tj = out / "ns_data" / "transforms.json"
    if not tj.exists():
        raise PipelineError(f"{tj} not found.", "Run the reconstruct stage first.")
    T = json.loads(tj.read_text())
    frames = T["frames"]
    c2w = np.array([f["transform_matrix"] for f in frames], dtype=np.float64)
    dps = sorted(out.glob("train/**/dataparser_transforms.json"), key=lambda p: p.stat().st_mtime)
    pos, rot = c2w[:, :3, 3].copy(), c2w[:, :3, :3].copy()
    if dps:
        dp = json.loads(dps[-1].read_text()); M = np.array(dp["transform"], dtype=np.float64); s = float(dp["scale"])
        pos = s * (pos @ M[:3, :3].T + M[:3, 3]); rot = M[:3, :3] @ rot
    else:
        log.warning("dataparser_transforms.json not found; assuming splat frame == transforms.json frame.")
    K = {k: T[k] for k in ("fl_x", "fl_y", "cx", "cy", "k1", "k2", "p1", "p2") if k in T}
    return {"pos": pos, "rot": rot, "K": K, "files": [f["file_path"] for f in frames], "data_dir": out / "ns_data"}

# ---------- floor ----------
def fit_floor(pts: np.ndarray, up: np.ndarray, frac: float, rel_thresh: float, iters: int = 3000,
              max_angle_deg: float = 30.0, seed: int = 0) -> tuple[np.ndarray, float, float]:
    """RANSAC plane on the lowest `frac` of points along `up`. Returns (unit normal pointing up, d, inlier ratio)."""
    rng = np.random.default_rng(seed)
    h = pts @ up
    low = pts[h <= np.quantile(h, frac)]
    if len(low) < 100:
        raise PipelineError("Too few points to fit a floor.", "Check the splat export is not empty.")
    ext = float(np.max(np.percentile(pts, 95, 0) - np.percentile(pts, 5, 0)))
    thr = rel_thresh * ext
    sub = low[rng.choice(len(low), min(len(low), 8000), replace=False)].astype(np.float32)
    tri = rng.integers(0, len(sub), (iters, 3))
    n = np.cross(sub[tri[:, 1]] - sub[tri[:, 0]], sub[tri[:, 2]] - sub[tri[:, 0]])
    nn = np.linalg.norm(n, axis=1); ok = nn > 1e-9
    n[ok] /= nn[ok, None]; n[~ok] = 0
    n[(n @ up.astype(np.float32)) < 0] *= -1
    ok &= (n @ up.astype(np.float32)) > np.cos(np.radians(max_angle_deg))
    if not ok.any():
        raise PipelineError("RANSAC found no plausible floor.", "Floor may be barely visible; capture more floor (SOP) or raise align.floor_search_fraction.")
    n, tri = n[ok], tri[ok]
    best, best_cnt = None, -1
    for s in range(0, len(n), 200):
        nb, tb = n[s:s + 200], tri[s:s + 200]
        d = -np.einsum("ij,ij->i", nb, sub[tb[:, 0]])
        cnt = (np.abs(sub @ nb.T + d) < thr).sum(0)
        i = int(cnt.argmax())
        if cnt[i] > best_cnt: best_cnt, best = int(cnt[i]), (nb[i].astype(np.float64), float(d[i]))
    nrm, d = best
    inl = low[np.abs(low @ nrm + d) < thr]
    c = inl.mean(0); _, _, vt = np.linalg.svd(inl - c, full_matrices=False)   # refit on inliers
    nrm = vt[2] if vt[2] @ up > 0 else -vt[2]
    return nrm, float(-nrm @ c), len(inl) / len(low)

# ---------- scale from a marker ----------
def detect_tag_scale(cams: dict, tag_size_m: str | float, family: str, max_images: int = 150) -> dict | None:
    """Triangulate marker corners from camera rays; returns metres-per-splat-unit and a confidence, or None."""
    name = TAG_DICTS.get(family)
    if name is None or not hasattr(cv2, "aruco"):
        log.warning("Marker detection unavailable (family=%s, cv2.aruco=%s).", family, hasattr(cv2, "aruco")); return None
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name)), cv2.aruco.DetectorParameters())
    K = cams["K"]
    if not all(k in K for k in ("fl_x", "fl_y", "cx", "cy")): return None
    Km = np.array([[K["fl_x"], 0, K["cx"]], [0, K["fl_y"], K["cy"]], [0, 0, 1]], dtype=np.float64)
    dist = np.array([K.get("k1", 0), K.get("k2", 0), K.get("p1", 0), K.get("p2", 0)], dtype=np.float64)
    idxs = np.linspace(0, len(cams["files"]) - 1, min(max_images, len(cams["files"]))).round().astype(int)
    hits: dict[int, list] = {}
    for i in idxs:
        img = cv2.imread(str(cams["data_dir"] / cams["files"][i]), cv2.IMREAD_GRAYSCALE)
        if img is None: continue
        corners, ids, _ = det.detectMarkers(img)
        if ids is None: continue
        for c, tid in zip(corners, ids.ravel()):
            und = cv2.undistortPoints(c.reshape(-1, 1, 2).astype(np.float64), Km, dist, P=Km).reshape(4, 2)
            d_cam = np.stack([(und[:, 0] - Km[0, 2]) / Km[0, 0], -(und[:, 1] - Km[1, 2]) / Km[1, 1], -np.ones(4)], 1)
            d = d_cam @ cams["rot"][i].T; d /= np.linalg.norm(d, axis=1, keepdims=True)
            hits.setdefault(int(tid), []).append((cams["pos"][i], d))
    if not hits: return None
    tid = max(hits, key=lambda k: len(hits[k]))
    obs = hits[tid]
    if len(obs) < 3:
        log.warning("Marker %d seen in only %d images (need >=3).", tid, len(obs)); return None
    P, res = [], []
    for k in range(4):
        A, b = np.zeros((3, 3)), np.zeros(3)
        for o, d in obs:
            M = np.eye(3) - np.outer(d[k], d[k]); A += M; b += M @ o
        if np.linalg.cond(A) > 1e8: return None   # rays (near-)parallel: no baseline
        x = np.linalg.solve(A, b); P.append(x)
        res.append(np.mean([np.linalg.norm((np.eye(3) - np.outer(d[k], d[k])) @ (x - o)) for o, d in obs]))
    P = np.array(P); sides = np.linalg.norm(P - np.roll(P, -1, 0), axis=1); side = float(sides.mean())
    cv_ = float(sides.std() / side); rr = float(np.mean(res) / side)
    conf = float(np.clip(1 - 4 * cv_ - 2 * rr, 0, 1) * min(1.0, len(obs) / 8))
    return {"scale": float(tag_size_m) / side, "tag_id": tid, "views": len(obs), "side_units": side,
            "side_cv": cv_, "residual_rel": rr, "confidence": round(conf, 3)}

# ---------- main ----------
def align(cfg: dict, out: Path) -> dict:
    a = cfg["align"]
    d = read_gs_ply(out / "splat.ply")
    cams = load_cameras(out)
    up = (cams["rot"][:, :, 1]).mean(0); up /= np.linalg.norm(up)       # OpenGL camera +Y = up
    n, off, inl = fit_floor(d["xyz"], up, a["floor_search_fraction"], a["floor_ransac_thresh"])
    R = rot_between(n, np.array([0.0, 1.0, 0.0]))
    ext = float(np.max(np.percentile(d["xyz"], 95, 0) - np.percentile(d["xyz"], 5, 0)))
    floor_pts = d["xyz"][np.abs(d["xyz"] @ n + off) < a["floor_ransac_thresh"] * ext]
    y0 = float(np.median((floor_pts @ R.T)[:, 1]))
    cam_up_dev = float(np.degrees(np.arccos(np.clip((R @ up)[1], -1, 1))))
    if cam_up_dev > 35:
        log.warning("Camera-up vs floor normal differ by %.0f deg: floor may be wrong (ceiling/wall?).", cam_up_dev)
    cam_p = cams["pos"] @ R.T; cam_p[:, 1] -= y0
    tag = detect_tag_scale(cams, a["tag_size_m"], a["tag_family"])
    if tag:
        s, method, approx, conf = tag["scale"], "apriltag", False, tag["confidence"]
        log.info("Scale from marker id %d: %.4f m/unit (conf %.2f, %d views)", tag["tag_id"], s, conf, tag["views"])
    else:
        hmed = float(np.median(cam_p[:, 1]))
        if hmed <= 0: raise PipelineError("Camera heights are non-positive after floor alignment.", "Floor fit is likely wrong; check out/debug/floor_alignment.png.")
        s, method, approx, conf = a["fallback_camera_height_m"] / hmed, "camera_height_fallback", True, 0.3
        log.warning("No usable marker: scale is APPROXIMATE (median camera height := %.2f m).", a["fallback_camera_height_m"])
    # apply similarity  p' = s * (R p - y0*e_y)
    q = mat_to_quat(R)
    xyz = d["xyz"] @ R.T; xyz[:, 1] -= y0; xyz *= s
    d2 = {"xyz": xyz, "dc": d["dc"], "opacity": d["opacity"], "scale": d["scale"] + np.log(s),
          "rot": quat_mul(q, d["rot"])}
    d2["rest"] = rotate_sh1(d["rest"], R) if d["rest"].shape[2] >= 3 else d["rest"]
    write_gs_ply(out / "aligned.ply", d2, sh_degree=1)
    cp = cam_p * s
    fwd = -(cams["rot"][:, :, 2] @ R.T)                                   # OpenGL forward = -Z
    (out / "cameras_aligned.json").write_text(json.dumps({"positions": cp.round(4).tolist(), "forward": fwd.round(4).tolist()}))
    M4 = np.eye(4); M4[:3, :3] = s * R; M4[:3, 3] = [0, -y0 * s, 0]
    lo, hi = xyz.min(0), xyz.max(0)
    tr = {"matrix": M4.tolist(), "rotation": R.tolist(), "scale": s, "method": method, "approximate": approx,
          "confidence": conf, "tag": tag, "floor_inlier_ratio": round(inl, 4), "camera_up_deviation_deg": round(cam_up_dev, 2),
          "bounds": {"min": lo.round(3).tolist(), "max": hi.round(3).tolist()}, "median_camera_height_m": float(np.median(cp[:, 1]))}
    (out / "transform.json").write_text(json.dumps(tr, indent=2))
    _debug_plot(out, xyz, cp, lo, hi)
    log.info("Aligned: scale %.4f (%s), bounds %s..%s m", s, method, lo.round(2), hi.round(2))
    return tr

def _debug_plot(out: Path, xyz: np.ndarray, cp: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> None:
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sub = xyz[np.random.default_rng(0).choice(len(xyz), min(len(xyz), 20000), replace=False)]
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.5))
    ax[0].scatter(sub[:, 0], sub[:, 1], s=0.3, c="gray"); ax[0].axhline(0, c="r", label="floor Y=0")
    ax[0].scatter(cp[:, 0], cp[:, 1], s=4, c="g", label="cameras"); ax[0].set_title("Side view (X vs Y, metres)"); ax[0].legend(); ax[0].set_aspect("equal")
    ax[1].scatter(sub[:, 0], sub[:, 2], s=0.3, c="gray"); ax[1].plot(cp[:, 0], cp[:, 2], "g-", lw=1)
    ax[1].add_patch(plt.Rectangle((lo[0], lo[2]), hi[0] - lo[0], hi[2] - lo[2], fill=False, ec="b")); ax[1].set_title("Top view (X vs Z) + bounding box"); ax[1].set_aspect("equal")
    (out / "debug").mkdir(exist_ok=True); fig.tight_layout(); fig.savefig(out / "debug" / "floor_alignment.png", dpi=110); plt.close(fig)

def run(cfg: dict, out: Path, inputs: list[Path]) -> dict:
    """Stage entry point."""
    t = align(cfg, out)
    return {"scale_method": t["method"], "scale_factor": round(t["scale"], 5), "approximate": t["approximate"],
            "confidence": t["confidence"], "floor_inlier_ratio": t["floor_inlier_ratio"]}
