"""Read/write 3D Gaussian Splatting PLY files (Nerfstudio/gsplat layout) as plain numpy arrays.
Own minimal binary-little-endian PLY I/O (no plyfile: it is GPL-3.0, we only use permissive licences)."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from utils import PipelineError

SH_C0 = 0.28209479177387814

_PLY_T = {"float": "<f4", "float32": "<f4", "double": "<f8", "float64": "<f8", "uchar": "u1", "uint8": "u1", "char": "i1", "int8": "i1",
          "short": "<i2", "int16": "<i2", "ushort": "<u2", "uint16": "<u2", "int": "<i4", "int32": "<i4", "uint": "<u4", "uint32": "<u4"}

def _read_vertex_table(path: Path) -> np.ndarray:
    """Parse a binary_little_endian PLY and return the 'vertex' element as a structured array."""
    if not Path(path).is_file():
        raise PipelineError(f"Required file not found: {path}", "Run the earlier pipeline stages first (or re-run without --resume).")
    raw = Path(path).read_bytes()
    end = raw.find(b"end_header")
    if not raw.startswith(b"ply") or end < 0:
        raise PipelineError(f"{path} is not a PLY file.", "Re-run the previous stage.")
    hdr_end = raw.index(b"\n", end) + 1
    fmt, count, fields, in_vertex = "", 0, [], False
    for line in raw[:hdr_end].decode("ascii", "ignore").splitlines():
        t = line.split()
        if t[:1] == ["format"]: fmt = t[1]
        elif t[:1] == ["element"]: in_vertex = t[1] == "vertex"; count = int(t[2]) if in_vertex else count
        elif t[:1] == ["property"] and in_vertex:
            if t[1] == "list" or t[1] not in _PLY_T:
                raise PipelineError(f"Unsupported PLY property: {line}", "Export with `ns-export gaussian-splat`.")
            fields.append((t[2], _PLY_T[t[1]]))
    if fmt != "binary_little_endian":
        raise PipelineError(f"PLY format '{fmt}' unsupported (need binary_little_endian).", "Re-export the splat as a standard binary PLY.")
    dt = np.dtype(fields)
    if len(raw) - hdr_end < count * dt.itemsize:
        raise PipelineError(f"{path} is truncated.", "Re-run the previous stage.")
    return np.frombuffer(raw, dtype=dt, count=count, offset=hdr_end)

def read_gs_ply(path: Path) -> dict[str, np.ndarray]:
    """Return dict: xyz(N,3), dc(N,3), rest(N,3,K-1), opacity(N,) logit, scale(N,3) log, rot(N,4) wxyz."""
    v = _read_vertex_table(path)
    names = v.dtype.names
    need = ["x", "y", "z", "f_dc_0", "opacity", "scale_0", "rot_0"]
    miss = [n for n in need if n not in names]
    if miss:
        raise PipelineError(f"{path} is not a Gaussian splat PLY (missing {miss}).", "Export with `ns-export gaussian-splat`.")
    n = len(v)
    nr = len([k for k in names if k.startswith("f_rest_")]) // 3
    rest = np.zeros((n, 3, nr))
    for c in range(3):
        for j in range(nr):
            rest[:, c, j] = v[f"f_rest_{c * nr + j}"]
    rot = np.stack([v[f"rot_{i}"] for i in range(4)], 1).astype(np.float64)
    rot /= np.maximum(np.linalg.norm(rot, axis=1, keepdims=True), 1e-12)
    return {"xyz": np.stack([v["x"], v["y"], v["z"]], 1).astype(np.float64),
            "dc": np.stack([v[f"f_dc_{i}"] for i in range(3)], 1).astype(np.float64), "rest": rest,
            "opacity": np.asarray(v["opacity"], dtype=np.float64),
            "scale": np.stack([v[f"scale_{i}"] for i in range(3)], 1).astype(np.float64), "rot": rot}

def write_gs_ply(path: Path, d: dict[str, np.ndarray], sh_degree: int = 1) -> None:
    """Write Gaussians; keeps SH bands up to `sh_degree` (<= bands available)."""
    keep = min((sh_degree + 1) ** 2 - 1, d["rest"].shape[2])
    n = len(d["xyz"])
    cols: dict[str, np.ndarray] = {"x": d["xyz"][:, 0], "y": d["xyz"][:, 1], "z": d["xyz"][:, 2]}
    for i in range(3): cols[f"f_dc_{i}"] = d["dc"][:, i]
    for c in range(3):
        for j in range(keep): cols[f"f_rest_{c * keep + j}"] = d["rest"][:, c, j]
    cols["opacity"] = d["opacity"]
    for i in range(3): cols[f"scale_{i}"] = d["scale"][:, i]
    for i in range(4): cols[f"rot_{i}"] = d["rot"][:, i]
    arr = np.empty(n, dtype=[(k, "<f4") for k in cols])
    for k, val in cols.items(): arr[k] = val
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    hdr = "ply\nformat binary_little_endian 1.0\n" + f"element vertex {n}\n" + "".join(f"property float {k}\n" for k in cols) + "end_header\n"
    with open(path, "wb") as f:
        f.write(hdr.encode("ascii")); f.write(arr.tobytes())

def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))
