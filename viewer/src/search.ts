/**
 * search.ts: Pure ranking and fuzzy search for POIs.
 *
 * Matching tiers (strictly ordered):
 * 1. exact     - query exactly equals name
 * 2. prefix    - name starts with query
 * 3. token     - one of the words in name starts with / equals query
 * 4. alias     - exact or prefix match on any alias
 * 5. category  - query matches POI category
 * 6. fuzzy     - Levenshtein distance <= 1-2 on name, token, or alias
 */
import type { ValidatedPOI } from "./poi";

export type MatchTier = "exact" | "prefix" | "token" | "alias" | "category" | "fuzzy";

export interface SearchResult {
  poi: ValidatedPOI;
  tier: MatchTier;
  distance: number; // distance in metres to player
  matchScore: number; // lower rank tier number is better (1 to 6)
}

export function normalise(str: string): string {
  return str
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, " ");
}

/** Compute Levenshtein distance between two strings. */
export function levenshtein(a: string, b: string): number {
  const la = a.length;
  const lb = b.length;
  if (la === 0) return lb;
  if (lb === 0) return la;

  // Use single row allocation
  let prevRow = new Int32Array(lb + 1);
  let currRow = new Int32Array(lb + 1);

  for (let j = 0; j <= lb; j++) {
    prevRow[j] = j;
  }

  for (let i = 1; i <= la; i++) {
    currRow[0] = i;
    const ca = a.charCodeAt(i - 1);
    for (let j = 1; j <= lb; j++) {
      const cb = b.charCodeAt(j - 1);
      const cost = ca === cb ? 0 : 1;
      currRow[j] = Math.min(
        currRow[j - 1] + 1, // insertion
        prevRow[j] + 1, // deletion
        prevRow[j - 1] + cost // substitution
      );
    }
    const tmp = prevRow;
    prevRow = currRow;
    currRow = tmp;
  }

  return prevRow[lb];
}

/** Max allowed typos depending on query length. */
function maxAllowedTypos(len: number): number {
  if (len <= 3) return 0;
  if (len <= 6) return 1;
  return 2;
}

export function matchPOI(queryNorm: string, poi: ValidatedPOI): MatchTier | null {
  if (!queryNorm) return null;

  const nameNorm = normalise(poi.name);
  if (nameNorm === queryNorm) return "exact";

  if (nameNorm.startsWith(queryNorm)) return "prefix";

  const tokens = nameNorm.split(" ");
  for (const token of tokens) {
    if (token.startsWith(queryNorm)) return "token";
  }

  const aliases = (poi.aliases ?? []).map(normalise);
  for (const alias of aliases) {
    if (alias === queryNorm || alias.startsWith(queryNorm)) {
      return "alias";
    }
  }

  const categoryNorm = normalise(poi.category);
  if (categoryNorm === queryNorm || categoryNorm.startsWith(queryNorm)) {
    return "category";
  }

  // Fuzzy match (Levenshtein)
  const allowed = maxAllowedTypos(queryNorm.length);
  if (allowed > 0) {
    if (levenshtein(queryNorm, nameNorm) <= allowed) return "fuzzy";
    for (const token of tokens) {
      if (levenshtein(queryNorm, token) <= allowed) return "fuzzy";
    }
    for (const alias of aliases) {
      if (levenshtein(queryNorm, alias) <= allowed) return "fuzzy";
    }
  }

  return null;
}

const TIER_RANK: Record<MatchTier, number> = {
  exact: 1,
  prefix: 2,
  token: 3,
  alias: 4,
  category: 5,
  fuzzy: 6,
};

export function searchPOIs(
  rawQuery: string,
  pois: ValidatedPOI[],
  playerX?: number,
  playerZ?: number
): SearchResult[] {
  const query = normalise(rawQuery);
  if (!query) {
    // If empty query, list all POIs sorted by distance to player
    return pois.map((poi) => {
      const dist =
        playerX !== undefined && playerZ !== undefined
          ? Math.hypot(poi.worldPos[0] - playerX, poi.worldPos[1] - playerZ)
          : 0;
      return {
        poi,
        tier: "exact" as MatchTier,
        distance: dist,
        matchScore: 1,
      };
    }).sort((a, b) => a.distance - b.distance);
  }

  const results: SearchResult[] = [];

  for (const poi of pois) {
    const tier = matchPOI(query, poi);
    if (!tier) continue;

    const dist =
      playerX !== undefined && playerZ !== undefined
        ? Math.hypot(poi.worldPos[0] - playerX, poi.worldPos[1] - playerZ)
        : 0;

    results.push({
      poi,
      tier,
      distance: dist,
      matchScore: TIER_RANK[tier],
    });
  }

  // Sort by tier priority first, then by physical distance
  results.sort((a, b) => {
    if (a.matchScore !== b.matchScore) {
      return a.matchScore - b.matchScore;
    }
    return a.distance - b.distance;
  });

  return results;
}
