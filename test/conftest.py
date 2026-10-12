"""Shared fixtures: synthetic walkthrough video (pan + stationary segment + blurred segment)."""
import cv2, numpy as np, pytest

@pytest.fixture(scope="session")
def synth_video(tmp_path_factory):
    p = tmp_path_factory.mktemp("vid") / "synth.mp4"
    rng = np.random.default_rng(0)
    world = cv2.GaussianBlur(rng.integers(0, 255, (900, 2400, 3), dtype=np.uint8), (0, 0), 1.2)
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 30, (640, 480))
    for i in range(300):  # 10 s
        x = 0 if 100 <= i < 160 else (min(i, 100) if i < 100 else i - 60)  # stationary 100-160
        f = world[200:680, x * 6: x * 6 + 640].copy()
        if 200 <= i < 230:
            f = cv2.GaussianBlur(f, (0, 0), 8)  # motion-blur-like segment
        w.write(f)
    w.release()
    return p
