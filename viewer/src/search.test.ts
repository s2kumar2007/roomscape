import { describe, it, expect } from "vitest";
import { normalise, levenshtein, matchPOI, searchPOIs } from "./search";
import type { ValidatedPOI } from "./poi";

describe("Search Pure Functions and Ranking", () => {
  const samplePOIs: ValidatedPOI[] = [
    {
      id: "entrance",
      name: "Main Entrance",
      category: "door",
      aliases: ["exit", "doorway"],
      position: [0.65, -4.25],
      worldPos: [0.65, -4.25],
      originalPos: [0.65, -4.25],
      snapDist: 0,
    },
    {
      id: "desk",
      name: "Workstation Desk",
      category: "desk",
      aliases: ["computer", "table"],
      position: [1.5, -3.5],
      worldPos: [1.5, -3.5],
      originalPos: [1.5, -3.5],
      snapDist: 0,
    },
    {
      id: "lounge",
      name: "Lounge Seating",
      category: "seating",
      aliases: ["sofa", "couch"],
      position: [3.5, -4.5],
      worldPos: [3.5, -4.5],
      originalPos: [3.5, -4.5],
      snapDist: 0,
    },
    {
      id: "coffee",
      name: "Coffee Corner",
      category: "amenity",
      aliases: ["kitchen", "pantry"],
      position: [4.5, -5.15],
      worldPos: [4.5, -5.15],
      originalPos: [4.5, -5.15],
      snapDist: 0,
    },
  ];

  it("normalises strings properly", () => {
    expect(normalise("  Main   Entrance! ")).toBe("main entrance");
    expect(normalise("Café / Coffee?")).toBe("caf coffee");
  });

  it("computes accurate Levenshtein distances", () => {
    expect(levenshtein("", "")).toBe(0);
    expect(levenshtein("kitten", "sitting")).toBe(3);
    expect(levenshtein("entrance", "entrence")).toBe(1);
    expect(levenshtein("desk", "dask")).toBe(1);
  });

  it("ranks exact match higher than prefix match", () => {
    const pois: ValidatedPOI[] = [
      {
        id: "p1",
        name: "Desk",
        category: "furniture",
        position: [1, 1],
        worldPos: [1, 1],
        originalPos: [1, 1],
        snapDist: 0,
      },
      {
        id: "p2",
        name: "Desktop Monitor",
        category: "electronics",
        position: [2, 2],
        worldPos: [2, 2],
        originalPos: [2, 2],
        snapDist: 0,
      },
    ];
    const results = searchPOIs("desk", pois);
    expect(results.length).toBe(2);
    expect(results[0].poi.id).toBe("p1");
    expect(results[0].tier).toBe("exact");
    expect(results[1].poi.id).toBe("p2");
    expect(results[1].tier).toBe("prefix");
  });

  it("ranks prefix higher than token, and token higher than alias", () => {
    const results = searchPOIs("work", samplePOIs);
    expect(results.length).toBeGreaterThan(0);
    expect(results[0].poi.id).toBe("desk");
    expect(results[0].tier).toBe("prefix");

    const tokenRes = searchPOIs("desk", samplePOIs);
    expect(tokenRes[0].poi.id).toBe("desk");
    // "Workstation Desk" -> token match on second word
    expect(tokenRes[0].tier).toBe("token");

    const aliasRes = searchPOIs("sofa", samplePOIs);
    expect(aliasRes[0].poi.id).toBe("lounge");
    expect(aliasRes[0].tier).toBe("alias");
  });

  it("ranks category higher than fuzzy match", () => {
    const catRes = searchPOIs("amenity", samplePOIs);
    expect(catRes[0].poi.id).toBe("coffee");
    expect(catRes[0].tier).toBe("category");

    // Typo: "entrence" -> fuzzy match
    const fuzzyRes = searchPOIs("entrence", samplePOIs);
    expect(fuzzyRes.length).toBeGreaterThan(0);
    expect(fuzzyRes[0].poi.id).toBe("entrance");
    expect(fuzzyRes[0].tier).toBe("fuzzy");
  });

  it("sorts by distance when tiers are equal", () => {
    const playerX = 0.0;
    const playerZ = 0.0;
    const all = searchPOIs("", samplePOIs, playerX, playerZ);
    expect(all.length).toBe(4);
    for (let i = 1; i < all.length; i++) {
      expect(all[i].distance).toBeGreaterThanOrEqual(all[i - 1].distance);
    }
  });
});
