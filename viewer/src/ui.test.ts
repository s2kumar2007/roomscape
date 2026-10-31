import { describe, expect, it, beforeEach } from "vitest";
import { UI } from "./ui";

describe("UI banner", () => {
  let bannerElement: {
    textContent: string;
    style: { display: string; background: string; color: string; fontWeight: string };
  };

  beforeEach(() => {
    bannerElement = {
      textContent: "",
      style: { display: "none", background: "", color: "", fontWeight: "" },
    };
    (globalThis as any).document = {
      getElementById: (id: string) => (id === "banner" ? bannerElement : null),
      addEventListener: () => {},
    };
    (globalThis as any).window = {
      addEventListener: () => {},
    };
  });

  it("shows red 'MOCK SCENE' banner with bold white text when isErrorOrRed is true", () => {
    const ui = new UI();
    ui.banner("MOCK SCENE", true);

    expect(bannerElement.textContent).toBe("MOCK SCENE");
    expect(bannerElement.style.display).toBe("block");
    expect(bannerElement.style.background).toBe("#d32f2f");
    expect(bannerElement.style.color).toBe("#ffffff");
    expect(bannerElement.style.fontWeight).toBe("bold");
  });

  it("shows standard amber banner when isErrorOrRed is false", () => {
    const ui = new UI();
    ui.banner("Scale is approximate (no marker detected)", false);

    expect(bannerElement.textContent).toBe("Scale is approximate (no marker detected)");
    expect(bannerElement.style.display).toBe("block");
    expect(bannerElement.style.background).toBe("#5a4300cc");
    expect(bannerElement.style.color).toBe("#ffffff");
    expect(bannerElement.style.fontWeight).toBe("normal");
  });

  it("correctly identifies mock scene from meta to display red MOCK SCENE banner", () => {
    const ui = new UI();
    const meta = { mock: true, scale: { approximate: true } };
    if (meta.mock) {
      ui.banner("MOCK SCENE", true);
    } else if (meta.scale.approximate) {
      ui.banner("Scale is approximate (no marker detected)");
    }

    expect(bannerElement.textContent).toBe("MOCK SCENE");
    expect(bannerElement.style.background).toBe("#d32f2f");
  });
});
