"""Synthetic test scene: a 6x4x2.6 m room (floor, walls, ceiling, table, ArUco/AprilTag on a wall), cameras walking
at 1.5 m, expressed in an arbitrary rotated/scaled/translated 'training frame' like Nerfstudio produces.
Usage: python test/synthetic.py <out_dir>   (produces out/splat.ply, out/ns_data/transforms.json, images)"""
from __future__ import annotations
import json, sys
from pathlib import Path
import cv2, numpy as np
sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))
from gsplat_io import write_gs_ply, SH_C0

SCALE = 0.37                        # training-frame units per metre (unknown to the pipeline)
TAG_M, TAG_ID = 0.20, 7
TAG_CENTER_M = np.array([3.0, 1.4, 0.02])   # on the wall z=0, facing +z

def _rotation(rng) -> np.ndarray:
    q = rng.normal(size=4); q /= np.linalg.norm(q); w, x, y, z = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)], [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)], [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

def room_points(rng, n=60000) -> tuple[np.ndarray, np.ndarray]:
    W, D, H = 6.0, 4.0, 2.6
    pts = [np.c_[rng.uniform(0, W, n//3), np.zeros(n//3), rng.uniform(0, D, n//3)]]          # floor y=0
    pts.append(np.c_[rng.uniform(0, W, n//10), np.full(n//10, H), rng.uniform(0, D, n//10)])  # ceiling
    for k in range(n//10):  # placeholder to keep shape logic simple
        break
    m = n // 12
    pts.append(np.c_[rng.uniform(0, W, m), rng.uniform(0, H, m), np.zeros(m)])               # wall z=0
    pts.append(np.c_[rng.uniform(0, W, m), rng.uniform(0, H, m), np.full(m, D)])             # wall z=D
    pts.append(np.c_[np.zeros(m), rng.uniform(0, H, m), rng.uniform(0, D, m)])               # wall x=0
    pts.append(np.c_[np.full(m, W), rng.uniform(0, H, m), rng.uniform(0, D, m)])             # wall x=W
    t = n // 12                                                                               # table 1.2x0.8, top at 0.75
    pts.append(np.c_[rng.uniform(2, 3.2, t), np.full(t, 0.75), rng.uniform(1.5, 2.3, t)])
    for lx, lz in ((2, 1.5), (3.2, 1.5), (2, 2.3), (3.2, 2.3)):                              # legs
        pts.append(np.c_[np.full(t//8, lx) + rng.normal(0, .01, t//8), rng.uniform(0, .75, t//8), np.full(t//8, lz) + rng.normal(0, .01, t//8)])
    P = np.vstack(pts); col = rng.uniform(0.2, 0.9, (len(P), 3))
    return P, col

def make(out: Path, seed: int = 0, with_images: bool = True, n_cams: int = 60) -> dict:
    rng = np.random.default_rng(seed)
    P, col = room_points(rng)
    R0, t0 = _rotation(rng), rng.normal(size=3) * 3          # metres -> training frame
    to_tf = lambda X: SCALE * (X @ R0.T + t0)
    xyz = to_tf(P); n = len(P)
    q = np.tile([1.0, 0, 0, 0], (n, 1))
    d = {"xyz": xyz, "dc": (col - 0.5) / SH_C0, "rest": np.zeros((n, 3, 3)), "opacity": np.full(n, 3.0) + rng.normal(0, .2, n),
         "scale": np.full((n, 3), np.log(0.02 * SCALE)), "rot": q}
    # sprinkle floaters (outliers) far away
    fl = 200; d["xyz"][:fl] = xyz.mean(0) + rng.normal(0, 8 * SCALE, (fl, 3)); d["opacity"][:fl] = 3.0
    (out / "ns_data" / "images").mkdir(parents=True, exist_ok=True)
    write_gs_ply(out / "splat.ply", d, sh_degree=1)
    fx = fy = 1000.0; w, h = 1280, 720
    frames, dict_ = [], cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    marker = cv2.aruco.generateImageMarker(dict_, TAG_ID, 200); marker = cv2.copyMakeBorder(marker, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    src = np.float32([[40, 40], [240, 40], [240, 240], [40, 240]])
    half = TAG_M / 2; tag3d = TAG_CENTER_M + np.array([[-half, half, 0], [half, half, 0], [half, -half, 0], [-half, -half, 0]])  # TL,TR,BR,BL as seen from +z
    for i in range(n_cams):
        a = i / (n_cams - 1)
        c = np.array([1.0 + 4.0 * a, 1.5, 1.5 + 0.3 * np.sin(6 * a)])
        look = np.array([3.0 + 0.5 * np.sin(3 * a), 1.3, 0.0]); f = look - c; f /= np.linalg.norm(f)
        z = -f; y = np.array([0, 1.0, 0]) - (np.array([0, 1.0, 0]) @ f) * f; y /= np.linalg.norm(y); x = np.cross(y, z)
        Rc = np.stack([x, y, z], 1)                           # camera->world (OpenGL), metres frame
        img = np.full((h, w), 200, np.uint8)
        if with_images:
            cam = (tag3d - c) @ Rc                            # world->camera
            uv = np.c_[fx * cam[:, 0] / -cam[:, 2] + w / 2, -fy * cam[:, 1] / -cam[:, 2] + h / 2].astype(np.float32)
            H_ = cv2.getPerspectiveTransform(src, uv)
            warped = cv2.warpPerspective(marker, H_, (w, h), flags=cv2.INTER_LINEAR, borderValue=200)
            mask = cv2.warpPerspective(np.full(marker.shape, 255, np.uint8), H_, (w, h))
            img = np.where(mask > 0, warped, img).astype(np.uint8)
            cv2.imwrite(str(out / "ns_data" / "images" / f"frame_{i:05d}.png"), img)
        Rtf = R0 @ Rc                                          # rotation in training frame
        frames.append({"file_path": f"images/frame_{i:05d}.png",
                       "transform_matrix": np.vstack([np.c_[Rtf, to_tf(c[None])[0]], [0, 0, 0, 1]]).tolist()})
    tj = {"fl_x": fx, "fl_y": fy, "cx": w / 2, "cy": h / 2, "w": w, "h": h, "frames": frames}
    (out / "ns_data" / "transforms.json").write_text(json.dumps(tj))
    return {"scale_true_m_per_unit": 1 / SCALE, "R0": R0, "t0": t0}

if __name__ == "__main__":
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True); make(out); print("synthetic scene ->", out)
