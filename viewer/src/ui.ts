/** DOM UI: loading screen, help (H or ?), FPS counter (F), fullscreen, reset, scale banner. */
const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;

export class UI {
  private help = $("help"); private fpsEl = $("fps");
  constructor(private onReset: () => void) {
    window.addEventListener("keydown", (e) => {
      if (e.key === "?" || e.key.toLowerCase() === "h" || e.code === "KeyH" || (e.code === "Slash" && e.shiftKey)) {
        e.preventDefault();
        this.toggleHelp();
      }
      if (e.code === "KeyF") this.fpsEl.style.display = this.fpsEl.style.display === "block" ? "none" : "block";
      if (e.code === "KeyR") this.onReset();
    });
    $("btn-reset").onclick = () => this.onReset();
    $("btn-help").onclick = () => this.toggleHelp();
    $("btn-full").onclick = () => { if (document.fullscreenElement) void document.exitFullscreen(); else void document.documentElement.requestFullscreen?.(); };
    document.addEventListener("pointerlockchange", () => { $("hint").style.display = document.pointerLockElement ? "none" : "block"; });
  }
  toggleHelp(): void { this.help.style.display = this.help.style.display === "block" ? "none" : "block"; }
  progress(frac: number, label: string): void { $("fill").style.width = `${Math.round(frac * 100)}%`; $("status").textContent = label; }
  done(): void { $("loading").classList.add("done"); }
  error(msg: string): void { $("status").textContent = "Could not load the scene"; $("error").textContent = msg; }
  fps(fps: number, ratio: number): void { this.fpsEl.textContent = `${fps.toFixed(0)} FPS · res ${(ratio * 100).toFixed(0)}%`; }
  banner(text: string): void { const b = $("banner"); b.textContent = text; b.style.display = "block"; }
}
