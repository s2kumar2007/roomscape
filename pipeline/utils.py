"""Shared helpers: config loading, logging, stage runner with timing + resume markers."""
from __future__ import annotations
import copy, json, logging, time
from pathlib import Path
from typing import Any, Callable
import yaml

class PipelineError(RuntimeError):
    """Raised for expected failures; carries a human-readable fix suggestion."""
    def __init__(self, msg: str, fix: str = "") -> None:
        super().__init__(msg)
        self.fix = fix

def get_logger(name: str = "roomscape") -> logging.Logger:
    log = logging.getLogger(name)
    if not log.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
        log.addHandler(h); log.setLevel(logging.INFO)
    return log

def _merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out

def load_config(path: str | Path, mode: str = "fast") -> dict[str, Any]:
    """Load YAML config and apply the preset for `mode`."""
    cfg = yaml.safe_load(Path(path).read_text())
    presets = cfg.pop("presets", {})
    if mode not in presets:
        raise PipelineError(f"Unknown mode '{mode}'", f"Use one of: {list(presets)}")
    return _merge(cfg, presets[mode])

def run_stage(name: str, fn: Callable[[], dict | None], out: Path, resume: bool) -> dict:
    """Run one stage: log, time, write out/timings.json, and write a .done marker."""
    log = get_logger()
    marker = out / ".markers" / f"{name}.done"
    tpath = out / "timings.json"
    timings = json.loads(tpath.read_text()) if tpath.exists() else {}
    if resume and marker.exists():
        log.info("[%s] skipped (resume: marker found)", name)
        return timings.get(name, {})
    log.info("[%s] start", name)
    t0 = time.perf_counter()
    result = fn() or {}
    dt = round(time.perf_counter() - t0, 2)
    log.info("[%s] done in %.2fs", name, dt)
    timings[name] = {"seconds": dt, **result}
    tpath.write_text(json.dumps(timings, indent=2))
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("ok")
    return timings[name]
