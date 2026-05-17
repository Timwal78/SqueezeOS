/**
 * Internal VRF primitives shared by evaluators.ts and vrf.ts.
 * Not part of the public SDK surface — imported by name only.
 */

/** Deterministic string → non-negative integer (djb2 variant). */
export function hashToNumber(input: string): number {
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    hash = ((hash << 5) - hash + input.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

/** Fisher-Yates shuffle driven by a deterministic LCG seed. */
export function deterministicShuffle<T>(arr: T[], seed: number): T[] {
  let s = seed;
  for (let i = arr.length - 1; i > 0; i--) {
    s = (s * 1664525 + 1013904223) & 0xffffffff;
    const j = Math.abs(s) % (i + 1);
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}
