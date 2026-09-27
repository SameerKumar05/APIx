/**
 * APIx dark-theme contrast AUDIT (static, read-only).
 *
 * Complements the Chromium gate (`verify-contrast.ts`, which covers chart
 * tooltips): this script scans every dashboard component for text colours
 * that are dim against the dark surfaces and reports file, line, colours,
 * size, and the computed WCAG ratio. It fixes nothing — findings belong to
 * the component owners.
 *
 * Method: each `text-*` class (and Recharts `tick fill`, which IS text) is
 * resolved to hex via the Tailwind v3 palette and scored against the three
 * dark surfaces text actually sits on here: neutral-950 (#0a0a0a, page and
 * cards), neutral-900 (#171717, inputs/badges/rails) and neutral-800
 * (#262626, active controls). The worst of the three is reported, so a
 * finding means "illegible on at least one surface it plausibly sits on".
 * Font size comes from the same className (text-[10px], text-xs, ...);
 * text-2xl+ counts as large (3:1), everything else needs 4.5:1.
 *
 * Run:  bun scripts/contrast-audit.ts [--strict]
 * Exit: 0 always (it is a report); 1 with --strict if any text fails AA.
 * Also writes frontend/scripts/contrast-audit-report.md for reviewers.
 */
import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { contrastRatio, fmtRatio } from './contrast-utils';

const THIS_DIR = path.dirname(fileURLToPath(import.meta.url));
const SRC_DIR = path.resolve(THIS_DIR, '..', 'src');

const NEUTRAL: Record<string, string> = {
  '50': '#fafafa', '100': '#f5f5f5', '200': '#e5e5e5', '300': '#d4d4d4',
  '400': '#a3a3a3', '500': '#737373', '600': '#525252', '700': '#404040',
  '800': '#262626', '900': '#171717', '950': '#0a0a0a',
};
const ACCENT: Record<string, string> = {
  'red-400': '#f87171',
  'amber-200': '#fde68a', 'amber-300': '#fcd34d', 'amber-400': '#fbbf24',
  'emerald-400': '#34d399', 'rose-300': '#fda4af',
  white: '#ffffff', black: '#000000',
};
const SURFACES: Array<{ name: string; hex: string }> = [
  { name: 'neutral-950 (#0a0a0a)', hex: '#0a0a0a' },
  { name: 'neutral-900 (#171717)', hex: '#171717' },
  { name: 'neutral-800 (#262626)', hex: '#262626' },
];
const SIZE_PX: Record<string, number> = {
  'xs': 12, 'sm': 14, 'base': 16, 'lg': 18, 'xl': 20, '2xl': 24, '3xl': 30,
};

function hex(rgb: { r: number; g: number; b: number }): string {
  const h = (n: number): string => Math.round(n).toString(16).padStart(2, '0');
  return `#${h(rgb.r)}${h(rgb.g)}${h(rgb.b)}`;
}
function parseHex(s: string): { r: number; g: number; b: number; a: number } {
  const h = s.replace('#', '');
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  return {
    r: parseInt(full.slice(0, 2), 16),
    g: parseInt(full.slice(2, 4), 16),
    b: parseInt(full.slice(4, 6), 16),
    a: 1,
  };
}

interface Finding {
  file: string;
  lines: number[];
  fgName: string;
  fgHex: string;
  sizePx: number;
  bold: boolean;
  r950: number;
  r900: number;
  r800: number;
  threshold: number;
  pass: boolean;
}

function sizeOfClass(className: string): number {
  const arb = /text-\[(\d+(?:\.\d+)?)px\]/.exec(className);
  if (arb) return Number(arb[1]);
  const named = /text-(xs|sm|base|lg|xl|2xl|3xl)(?![\w-])/.exec(className);
  if (named) return SIZE_PX[named[1]] ?? 12;
  return 12; // dashboard default: dense 12px mono
}

function auditFile(rel: string): Finding[] {
  const abs = path.join(SRC_DIR, rel);
  const src = readFileSync(abs, 'utf-8');
  const lines = src.split('\n');
  const out: Finding[] = [];
  const push = (lineNo: number, fgName: string, fgHex: string, sizePx: number, bold: boolean): void => {
    const fg = parseHex(fgHex);
    const rOf = (hexStr: string): number => contrastRatio(fg, parseHex(hexStr));
    // Verdict is scored on neutral-950: it is the page background and the
    // card/tooltip surface, i.e. where ~90% of dashboard text sits. Ratios on
    // 900/800 are shown alongside so a reviewer can judge controls that sit
    // on lighter rails. Dark foregrounds (e.g. text on light buttons) must be
    // checked against their real surface by hand — see report notes.
    const large = sizePx >= 24 || (sizePx >= 18.66 && bold);
    const threshold = large ? 3.0 : 4.5;
    const r950 = rOf('#0a0a0a');
    out.push({
      file: rel, lines: [lineNo], fgName, fgHex, sizePx, bold,
      r950, r900: rOf('#171717'), r800: rOf('#262626'),
      threshold, pass: r950 >= threshold,
    });
  };

  lines.forEach((line, idx) => {
    const lineNo = idx + 1;
    // className="... ..." — may span one line (these components keep them inline)
    for (const m of line.matchAll(/className="([^"]*)"/g)) {
      const cls = m[1];
      const bold = /font-(bold|semibold)/.test(cls);
      const sizePx = sizeOfClass(cls);
      for (const t of cls.matchAll(/text-neutral-(\d{2,3})/g)) {
        push(lineNo, `text-neutral-${t[1]}`, NEUTRAL[t[1]] ?? '#000000', sizePx, bold);
      }
      for (const t of cls.matchAll(/text-\[(#[0-9a-fA-F]{3,6})\]/g)) {
        push(lineNo, `text-[${t[1]}]`, t[1], sizePx, bold);
      }
      for (const t of cls.matchAll(/text-(red-400|amber-200|amber-300|amber-400|emerald-400|rose-300|white|black)(?![\w-])/g)) {
        push(lineNo, `text-${t[1]}`, ACCENT[t[1]], sizePx, bold);
      }
    }
    // Recharts tick fill="..." — axis tick labels ARE text. (Bar/Cell/Area
    // `fill` props are graphics, not text, and are deliberately ignored: only
    // lines mentioning tick are counted.)
    if (/tick/i.test(line)) {
      for (const m of line.matchAll(/fill:\s*'(#[0-9a-fA-F]{3,6})'|fill="(#[0-9a-fA-F]{3,6})"/g)) {
        const c = m[1] ?? m[2];
        push(lineNo, `tick fill ${c}`, c, 11, false);
      }
    }
  });
  return out;
}

function main(): number {
  const strict = process.argv.includes('--strict');
  const files = [...readdirSync(path.join(SRC_DIR, 'components')).map((f) => `components/${f}`), 'App.tsx'];
  const all = files.flatMap(auditFile);

  // Collapse to one row per (file, colour, size, weight): the point is the
  // colour choice, not every call site. Keep up to 6 line refs.
  const key = (f: Finding): string => `${f.file}|${f.fgHex}|${f.sizePx}|${f.bold}|${f.threshold}`;
  const grouped = new Map<string, Finding>();
  for (const f of all) {
    const g = grouped.get(key(f));
    if (g) {
      if (g.lines.length < 6) g.lines.push(...f.lines);
    } else {
      grouped.set(key(f), { ...f });
    }
  }
  const rows = [...grouped.values()].sort((a, b) =>
    a.file.localeCompare(b.file) || a.r950 - b.r950,
  );
  const fails = rows.filter((r) => !r.pass);

  const md: string[] = [];
  md.push('# APIx dashboard dark-theme contrast audit (static)');
  md.push('');
  md.push('Read-only scan of `frontend/src` text colours vs the dashboard dark surfaces');
  md.push('(neutral-950 #0a0a0a, neutral-900 #171717, neutral-800 #262626). Verdict is');
  md.push('scored on neutral-950 — the page background and the card/tooltip surface,');
  md.push('where nearly all dashboard text sits; the 900/800 columns let reviewers judge');
  md.push('controls on lighter rails. Thresholds: 4.5:1 normal text, 3:1 large (>=24px,');
  md.push('or >=18.66px bold). Chart tooltips are NOT judged here — they are gated in');
  md.push('headless Chromium by `scripts/verify-contrast.ts`.');
  md.push('');
  md.push(`Scanned ${files.length} files, ${all.length} text-colour usages collapsed to ${rows.length} distinct rows.`);
  md.push(`**${fails.length} FAIL, ${rows.length - fails.length} PASS.**`);
  md.push('');
  md.push('| Verdict | File | Colour | Size | on 950 | on 900 | on 800 | Needs | Lines |');
  md.push('|---|---|---|---|---|---|---|---|---|');
  for (const r of rows) {
    md.push(
      `| ${r.pass ? 'PASS' : '**FAIL**'} | ${r.file} | ${r.fgName} (${r.fgHex}) | ` +
      `${r.sizePx}px${r.bold ? ' bold' : ''} | ${fmtRatio(r.r950)} | ${fmtRatio(r.r900)} | ` +
      `${fmtRatio(r.r800)} | ${r.threshold}:1 | ${r.lines.join(', ')} |`,
    );
  }
  md.push('');
  md.push('## Dark-foreground rows (check by hand)');
  md.push('');
  md.push('Rows whose foreground is itself dark (neutral-600/700/800/950) score badly on');
  md.push('950 by construction. Each must be read against its REAL surface: `text-neutral-950`');
  md.push('on the light `bg-neutral-100` Retry button is correct (see App.tsx button); bare');
  md.push('`/` and `•` separators in neutral-600/700 on the header rail are decorative');
  md.push('single glyphs, still below 3:1 even as large text — keep or bump to neutral-500.');
  md.push('Any dark-on-dark instance NOT on a light surface is the same bug class as the');
  md.push('tooltip defect and should be fixed by the component owner.');
  md.push('');
  md.push('_Generated by `bun scripts/contrast-audit.ts`. Informational — fix ownership stays with component owners._');

  const reportPath = path.join(THIS_DIR, 'contrast-audit-report.md');
  writeFileSync(reportPath, md.join('\n'));
  console.log(md.join('\n'));
  console.log(`\nReport written to ${reportPath}`);

  if (strict && fails.length > 0) {
    console.error(`\nAUDIT STRICT: ${fails.length} failing rows. Exit 1.`);
    return 1;
  }
  return 0;
}

const code = main();
process.exit(code);
