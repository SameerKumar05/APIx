/**
 * Shared WCAG contrast utilities for the APIx dark-theme contrast checks.
 *
 * Thresholds (WCAG 2.1, Success Criterion 1.4.3 / 1.4.6):
 * - Normal text (< 18.66px, or < 14pt bold): 4.5:1 (AA)
 * - Large text (>= 24px, or >= 18.66px/14pt bold): 3:1 (AA)
 *
 * Every tooltip on this dashboard renders at 10-12px, so the 4.5:1
 * threshold applies to all tooltip text. The large-text carve-out exists
 * only so empty-state glyphs (e.g. 30px "—") are judged fairly.
 */

export const NORMAL_TEXT_MIN_RATIO = 4.5;
export const LARGE_TEXT_MIN_RATIO = 3.0;
/** px size at which bold text counts as "large" (14pt ~= 18.66px). */
export const LARGE_BOLD_PX = 18.66;
/** px size at which any text counts as "large" (18pt ~= 24px). */
export const LARGE_PX = 24;

function channelToLinear(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}

/** Correct relative luminance per WCAG (sRGB). */
export function luminance(r: number, g: number, b: number): number {
  return 0.2126 * channelToLinear(r) + 0.7152 * channelToLinear(g) + 0.0722 * channelToLinear(b);
}

export interface RGB {
  r: number;
  g: number;
  b: number;
  a: number;
}

/** Parse `rgb(...)`, `rgba(...)`, `#rgb`, `#rrggbb` into components. */
export function parseColor(input: string): RGB | null {
  const s = input.trim().toLowerCase();
  const hex3 = /^#([0-9a-f]{3})$/i.exec(s);
  if (hex3) {
    const h = hex3[1];
    return {
      r: parseInt(h[0] + h[0], 16),
      g: parseInt(h[1] + h[1], 16),
      b: parseInt(h[2] + h[2], 16),
      a: 1,
    };
  }
  const hex6 = /^#([0-9a-f]{6})$/i.exec(s);
  if (hex6) {
    const h = hex6[1];
    return {
      r: parseInt(h.slice(0, 2), 16),
      g: parseInt(h.slice(2, 4), 16),
      b: parseInt(h.slice(4, 6), 16),
      a: 1,
    };
  }
  const m = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)$/.exec(s);
  if (m) {
    return {
      r: Number(m[1]),
      g: Number(m[2]),
      b: Number(m[3]),
      a: m[4] === undefined ? 1 : Number(m[4]),
    };
  }
  if (s === 'white') return { r: 255, g: 255, b: 255, a: 1 };
  if (s === 'black') return { r: 0, g: 0, b: 0, a: 1 };
  if (s === 'transparent') return { r: 0, g: 0, b: 0, a: 0 };
  return null;
}

/**
 * Composite a (possibly translucent) foreground over an opaque background.
 * Both inputs are already-resolved computed-style strings.
 */
export function compositeOver(fg: RGB, bg: RGB): RGB {
  const a = fg.a;
  return {
    r: fg.r * a + bg.r * (1 - a),
    g: fg.g * a + bg.g * (1 - a),
    b: fg.b * a + bg.b * (1 - a),
    a: 1,
  };
}

/** WCAG contrast ratio between two opaque colours. Always >= 1. */
export function contrastRatio(fg: RGB, bg: RGB): number {
  const l1 = luminance(fg.r, fg.g, fg.b);
  const l2 = luminance(bg.r, bg.g, bg.b);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

/** Convenience: ratio directly from two CSS colour strings. */
export function ratioOf(fgCss: string, bgCss: string): number | null {
  const fg = parseColor(fgCss);
  const bg = parseColor(bgCss);
  if (!fg || !bg) return null;
  const flat = fg.a < 1 ? compositeOver(fg, { ...bg, a: 1 }) : fg;
  return contrastRatio(flat, { ...bg, a: 1 });
}

export function thresholdFor(fontPx: number, fontWeight: number): number {
  const isLarge = fontPx >= LARGE_PX || (fontPx >= LARGE_BOLD_PX && fontWeight >= 700);
  return isLarge ? LARGE_TEXT_MIN_RATIO : NORMAL_TEXT_MIN_RATIO;
}

export function fmtRatio(r: number): string {
  return `${r.toFixed(2)}:1`;
}
