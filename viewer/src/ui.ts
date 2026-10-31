/** DOM UI: loading screen, help (H or ?), FPS counter (F), fullscreen, reset, scale banner. */
const $ = <T extends HTMLElement>(id: string): T | null =>
  typeof document !== "undefined" ? (document.getElementById(id) as T | null) : null;

export class UI {
  private help = $("help");
  private fpsEl = $("fps");

  constructor(private onReset: () => void = () => {}) {
    if (typeof window !== "undefined") {
      window.addEventListener("keydown", (e) => {
        if (e.key === "?" || e.key.toLowerCase() === "h" || e.code === "KeyH" || (e.code === "Slash" && e.shiftKey)) {
          e.preventDefault();
          this.toggleHelp();
        }
        if (e.code === "KeyF" && this.fpsEl) this.fpsEl.style.display = this.fpsEl.style.display === "block" ? "none" : "block";
        if (e.code === "KeyR") this.onReset();
      });
    }
    const btnReset = $("btn-reset");
    if (btnReset) btnReset.onclick = () => this.onReset();
    const btnHelp = $("btn-help");
    if (btnHelp) btnHelp.onclick = () => this.toggleHelp();
    const btnFull = $("btn-full");
    if (btnFull) {
      btnFull.onclick = () => {
        if (typeof document !== "undefined" && document.fullscreenElement) void document.exitFullscreen();
        else void document?.documentElement?.requestFullscreen?.();
      };
    }
    if (typeof document !== "undefined") {
      document.addEventListener("pointerlockchange", () => {
        const hint = $("hint");
        if (hint) hint.style.display = document.pointerLockElement ? "none" : "block";
      });
    }
  }

  toggleHelp(): void {
    if (this.help) this.help.style.display = this.help.style.display === "block" ? "none" : "block";
  }

  progress(frac: number, label: string): void {
    const fill = $("fill");
    if (fill) fill.style.width = `${Math.round(frac * 100)}%`;
    const status = $("status");
    if (status) status.textContent = label;
  }

  done(): void {
    const loading = $("loading");
    if (loading) loading.classList.add("done");
  }

  error(msg: string): void {
    const status = $("status");
    if (status) status.textContent = "Could not load the scene";
    const err = $("error");
    if (err) err.textContent = msg;
  }

  fps(fps: number, ratio: number): void {
    if (this.fpsEl) this.fpsEl.textContent = `${fps.toFixed(0)} FPS · res ${(ratio * 100).toFixed(0)}%`;
  }

  banner(text: string, isErrorOrRed: boolean = false): void {
    const b = $("banner");
    if (!b) return;
    b.textContent = text;
    if (isErrorOrRed) {
      b.style.background = "#d32f2f";
      b.style.color = "#ffffff";
      b.style.fontWeight = "bold";
    } else {
      b.style.background = "#5a4300cc";
      b.style.color = "#ffffff";
      b.style.fontWeight = "normal";
    }
    b.style.display = "block";
  }
}
