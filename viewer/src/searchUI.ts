/**
 * searchUI.ts: Search overlay modal with keyboard and touch navigation.
 *
 * Features:
 * - "/" opens search (without Shift; "?" is help)
 * - Releases pointer lock on open
 * - Up/Down arrows navigate results, Enter selects, Esc closes
 * - Results show distance from player and category badges
 * - Touch search button in HUD
 */
import { searchPOIs, type SearchResult } from "./search";
import type { ValidatedPOI } from "./poi";
import { isInputFocused } from "./controls";

export class SearchUI {
  private overlay: HTMLElement | null = null;
  private input: HTMLInputElement | null = null;
  private resultsList: HTMLElement | null = null;
  private currentResults: SearchResult[] = [];
  private selectedIndex = 0;
  private disposers: (() => void)[] = [];
  private pois: ValidatedPOI[] = [];
  private getPlayerPos: () => [number, number] = () => [0, 0];

  constructor(
    pois: ValidatedPOI[],
    getPlayerPos: () => [number, number],
    private onSelectPOI: (poi: ValidatedPOI) => void
  ) {
    this.pois = pois;
    this.getPlayerPos = getPlayerPos;

    if (typeof document === "undefined") return;

    this.createDOM();
    this.setupListeners();
  }

  setPOIs(pois: ValidatedPOI[]): void {
    this.pois = pois;
  }

  private createDOM(): void {
    this.overlay = document.createElement("div");
    this.overlay.id = "search-overlay";
    this.overlay.setAttribute("role", "dialog");
    this.overlay.setAttribute("aria-label", "Point of Interest Search");
    this.overlay.style.position = "fixed";
    this.overlay.style.top = "60px";
    this.overlay.style.left = "50%";
    this.overlay.style.transform = "translateX(-50%)";
    this.overlay.style.width = "min(480px, 92vw)";
    this.overlay.style.background = "rgba(11, 13, 16, 0.95)";
    this.overlay.style.border = "1px solid rgba(77, 163, 255, 0.5)";
    this.overlay.style.borderRadius = "10px";
    this.overlay.style.boxShadow = "0 8px 32px rgba(0,0,0,0.8)";
    this.overlay.style.padding = "12px";
    this.overlay.style.zIndex = "30";
    this.overlay.style.display = "none";
    this.overlay.style.backdropFilter = "blur(10px)";

    const header = document.createElement("div");
    header.style.display = "flex";
    header.style.alignItems = "center";
    header.style.gap = "8px";
    header.style.marginBottom = "8px";

    const searchIcon = document.createElement("span");
    searchIcon.textContent = "🔍";
    searchIcon.style.fontSize = "16px";
    header.appendChild(searchIcon);

    this.input = document.createElement("input");
    this.input.id = "search-input";
    this.input.type = "text";
    this.input.setAttribute("role", "combobox");
    this.input.setAttribute("aria-expanded", "false");
    this.input.setAttribute("aria-autocomplete", "list");
    this.input.setAttribute("aria-controls", "search-results");
    this.input.placeholder = "Search points of interest... (Esc to close)";
    this.input.style.flex = "1";
    this.input.style.background = "#1b2028";
    this.input.style.border = "1px solid #333d4d";
    this.input.style.borderRadius = "6px";
    this.input.style.color = "#ffffff";
    this.input.style.padding = "8px 12px";
    this.input.style.fontSize = "14px";
    this.input.style.outline = "none";
    header.appendChild(this.input);

    const closeBtn = document.createElement("button");
    closeBtn.textContent = "✕";
    closeBtn.setAttribute("aria-label", "Close search");
    closeBtn.style.background = "transparent";
    closeBtn.style.border = "none";
    closeBtn.style.color = "#888";
    closeBtn.style.fontSize = "16px";
    closeBtn.style.cursor = "pointer";
    closeBtn.onclick = () => this.close();
    header.appendChild(closeBtn);

    this.overlay.appendChild(header);

    this.resultsList = document.createElement("div");
    this.resultsList.id = "search-results";
    this.resultsList.setAttribute("role", "listbox");
    this.resultsList.style.maxHeight = "280px";
    this.resultsList.style.overflowY = "auto";
    this.resultsList.style.display = "flex";
    this.resultsList.style.flexDirection = "column";
    this.resultsList.style.gap = "4px";
    this.overlay.appendChild(this.resultsList);

    const footer = document.createElement("div");
    footer.id = "search-footer";
    footer.style.display = "flex";
    footer.style.justifyContent = "space-between";
    footer.style.alignItems = "center";
    footer.style.marginTop = "8px";
    footer.style.paddingTop = "8px";
    footer.style.borderTop = "1px solid #232a35";
    footer.style.fontSize = "11px";
    footer.style.color = "#7e8b9b";
    footer.innerHTML = `<span><b>↑ / ↓</b> Navigate</span> <span><b>Enter</b> Select</span> <span><b>Esc</b> Close</span>`;
    this.overlay.appendChild(footer);

    document.body.appendChild(this.overlay);
    this.disposers.push(() => this.overlay?.remove());

    // Connect HUD search button if available
    const existingBtn = document.getElementById("btn-search");
    if (existingBtn) {
      existingBtn.onclick = () => this.toggle();
    } else {
      const hud = document.getElementById("hud");
      if (hud) {
        const btnSearch = document.createElement("button");
        btnSearch.id = "btn-search";
        btnSearch.title = "Search POIs (/)";
        btnSearch.textContent = "🔍 Search";
        btnSearch.onclick = () => this.toggle();
        hud.insertBefore(btnSearch, hud.firstChild);
        this.disposers.push(() => btnSearch.remove());
      }
    }
  }

  private setupListeners(): void {
    const onKey = (e: KeyboardEvent) => {
      // Slash without shift opens search if not currently typing in another input
      if (e.code === "Slash" && !e.shiftKey && !isInputFocused()) {
        e.preventDefault();
        this.open();
        return;
      }

      if (!this.isOpen()) return;

      if (e.key === "Escape") {
        e.preventDefault();
        this.close();
        return;
      }

      if (e.key === "ArrowDown") {
        e.preventDefault();
        this.moveSelection(1);
        return;
      }

      if (e.key === "ArrowUp") {
        e.preventDefault();
        this.moveSelection(-1);
        return;
      }

      if (e.key === "Enter") {
        e.preventDefault();
        this.selectCurrent();
        return;
      }
    };

    window.addEventListener("keydown", onKey);
    this.disposers.push(() => window.removeEventListener("keydown", onKey));

    if (this.input) {
      this.input.addEventListener("input", () => {
        this.renderResults();
      });
    }
  }

  isOpen(): boolean {
    return this.overlay !== null && this.overlay.style.display === "block";
  }

  open(): void {
    if (!this.overlay || !this.input) return;

    // Release pointer lock so cursor is free for typing
    if (document.pointerLockElement) {
      void document.exitPointerLock?.();
    }

    this.overlay.style.display = "block";
    this.input.setAttribute("aria-expanded", "true");
    this.input.value = "";
    this.selectedIndex = 0;
    this.renderResults();
    setTimeout(() => this.input?.focus(), 10);
  }

  close(): void {
    if (!this.overlay) return;
    this.overlay.style.display = "none";
    if (this.input) {
      this.input.setAttribute("aria-expanded", "false");
      this.input.blur();
    }
  }

  toggle(): void {
    if (this.isOpen()) this.close();
    else this.open();
  }

  private moveSelection(delta: number): void {
    if (this.currentResults.length === 0) return;
    this.selectedIndex = (this.selectedIndex + delta + this.currentResults.length) % this.currentResults.length;
    this.updateSelectionDOM();
  }

  private selectCurrent(): void {
    if (this.currentResults.length === 0) return;
    const chosen = this.currentResults[this.selectedIndex];
    if (chosen) {
      this.close();
      this.onSelectPOI(chosen.poi);
    }
  }

  private renderResults(): void {
    if (!this.resultsList || !this.input) return;

    const query = this.input.value;
    const [px, pz] = this.getPlayerPos();
    this.currentResults = searchPOIs(query, this.pois, px, pz);
    this.selectedIndex = 0;

    this.resultsList.innerHTML = "";

    if (this.currentResults.length === 0) {
      const empty = document.createElement("div");
      empty.textContent = "No matching locations found.";
      empty.style.padding = "10px";
      empty.style.color = "#778";
      empty.style.fontSize = "13px";
      empty.style.textAlign = "center";
      this.resultsList.appendChild(empty);
      return;
    }

    this.currentResults.forEach((res, idx) => {
      const row = document.createElement("div");
      row.className = "search-item";
      row.setAttribute("role", "option");
      row.setAttribute("aria-selected", idx === this.selectedIndex ? "true" : "false");
      row.style.display = "flex";
      row.style.alignItems = "center";
      row.style.justifyContent = "space-between";
      row.style.padding = "8px 10px";
      row.style.borderRadius = "6px";
      row.style.cursor = "pointer";
      row.style.transition = "background 0.15s";
      row.style.border = "1px solid transparent";

      const left = document.createElement("div");
      left.style.display = "flex";
      left.style.alignItems = "center";
      left.style.gap = "8px";

      const nameSpan = document.createElement("span");
      nameSpan.style.fontWeight = "600";
      nameSpan.style.color = "#e8eaed";
      nameSpan.textContent = res.poi.name;
      left.appendChild(nameSpan);

      const catBadge = document.createElement("span");
      catBadge.textContent = res.poi.category;
      catBadge.style.fontSize = "11px";
      catBadge.style.background = "#232b38";
      catBadge.style.color = "#8ab4f8";
      catBadge.style.padding = "2px 6px";
      catBadge.style.borderRadius = "4px";
      left.appendChild(catBadge);

      row.appendChild(left);

      const right = document.createElement("div");
      right.style.display = "flex";
      right.style.alignItems = "center";
      right.style.gap = "8px";

      const distSpan = document.createElement("span");
      distSpan.textContent = `${res.distance.toFixed(1)} m`;
      distSpan.style.fontSize = "12px";
      distSpan.style.color = "#9aa0a6";
      right.appendChild(distSpan);

      row.appendChild(right);

      row.onmouseenter = () => {
        this.selectedIndex = idx;
        this.updateSelectionDOM();
      };

      row.onclick = () => {
        this.close();
        this.onSelectPOI(res.poi);
      };

      this.resultsList!.appendChild(row);
    });

    this.updateSelectionDOM();
  }

  private updateSelectionDOM(): void {
    if (!this.resultsList) return;
    const items = this.resultsList.children;
    for (let i = 0; i < items.length; i++) {
      const el = items[i] as HTMLElement;
      const isSelected = i === this.selectedIndex;
      el.setAttribute("aria-selected", isSelected ? "true" : "false");
      if (isSelected) {
        el.style.background = "#1f3a5f";
        el.style.borderColor = "#4da3ff";
      } else {
        el.style.background = "transparent";
        el.style.borderColor = "transparent";
      }
    }
  }

  dispose(): void {
    this.disposers.forEach((d) => d());
    this.overlay?.remove();
  }
}
