/**
 * APIx dark-theme tooltip contrast gate.
 *
 * What it does:
 *  1. Calibration self-test (no browser): asserts the WCAG math flags a
 *     known-bad pair (#000 on #0a0a0a) and passes a known-good pair
 *     (#fff on #0a0a0a). If calibration fails the CHECKER is broken and we
 *     exit 2 — a gate that cannot fail is worse than useless.
 *  2. Serves `scripts/contrast-probe.html` (every chart tab, mock data) via
 *     a local vite dev server — no backend needed.
 *  3. Drives headless Chromium (playwright-core; browsers already cached)
 *     over each chart: moves the mouse over bar/line geometry (with a
 *     synthetic-event fallback, because headless hover is unreliable),
 *     waits for the Recharts tooltip to render, then reads the COMPUTED
 *     background + text colours and computes WCAG contrast ratios.
 *  4. Prints an explicit PASS/FAIL per tab and exits 1 on any failure.
 *
 * Thresholds (WCAG 2.1 AA, documented in contrast-utils.ts):
 *  normal text (<18.66px or <14pt-bold): 4.5:1 — applies to ALL tooltips
 *  large text: 3:1
 *
 * Run:  bun scripts/verify-contrast.ts [--port 5199]
 * Env:  CHROME_PATH (override browser binary), CONTRAST_PROBE_PORT,
 *         CONTRAST_PROBE_PATH (probe page URL path; used by the negative control)
 */
import { spawn, type ChildProcess } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, type Browser, type Page, type ElementHandle } from 'playwright-core';
import {
  parseColor,
  compositeOver,
  contrastRatio,
  thresholdFor,
  fmtRatio,
  NORMAL_TEXT_MIN_RATIO,
} from './contrast-utils';

const THIS_DIR = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = path.resolve(THIS_DIR, '..');
const PROBE_PATH =
  process.env['CONTRAST_PROBE_PATH'] ?? '/scripts/contrast-probe.html';

const TABS: Array<{ key: string; title: string }> = [
  { key: 'overview', title: 'National Overview' },
  { key: 'routes', title: 'Trunk Routes (10)' },
  { key: 'econometrics', title: 'Econometrics & CPI Gap' },
  { key: 'elasticity', title: 'Booking Elasticity' },
  { key: 'arbitrage', title: 'Fare Arbitrage' },
  { key: 'telemetry', title: 'Crawler Telemetry' },
];

/** Recharts default-tooltip selectors the bug report calls out explicitly. */
const EXPLICIT_SELECTORS = [
  '.recharts-tooltip-label',
  '.recharts-tooltip-item-name',
  '.recharts-tooltip-item-value',
  '.recharts-tooltip-item',
];

interface TextSample {
  desc: string;
  color: string;
  fontPx: number;
  fontWeight: number;
  sample: string;
}

interface TooltipMeasurement {
  surfaceDesc: string;
  surfaceBg: string;
  texts: TextSample[];
}

interface ChromeSample extends TextSample {
  surfaceBg: string;
  surfaceDesc: string;
}

interface TabResult {
  key: string;
  title: string;
  activated: number;
  checks: Array<{
    tooltip: string;
    desc: string;
    fg: string;
    bg: string;
    ratio: number;
    threshold: number;
    pass: boolean;
  }>;
  errors: string[];
  pass: boolean;
}

// ---------------------------------------------------------------------------
// 1. Calibration: prove the gate can fail, without touching the repo tree.
// ---------------------------------------------------------------------------
function calibrate(): boolean {
  // Known-bad: the exact reported bug — near-black item text on #0a0a0a.
  const bad = contrastRatio(
    { r: 0, g: 0, b: 0, a: 1 },
    { r: 0x0a, g: 0x0a, b: 0x0a, a: 1 },
  );
  // Known-good: white label on #0a0a0a.
  const good = contrastRatio(
    { r: 255, g: 255, b: 255, a: 1 },
    { r: 0x0a, g: 0x0a, b: 0x0a, a: 1 },
  );
  console.log('[calibrate] known-bad  #000 on #0a0a0a = ' + fmtRatio(bad) + ` (must be < ${NORMAL_TEXT_MIN_RATIO})`);
  console.log('[calibrate] known-good #fff on #0a0a0a = ' + fmtRatio(good) + ` (must be >= ${NORMAL_TEXT_MIN_RATIO})`);
  if (!(bad < NORMAL_TEXT_MIN_RATIO)) {
    console.error('[calibrate] BROKEN: known-bad pair did not fail. Refusing to pass vacuously.');
    return false;
  }
  if (!(good >= NORMAL_TEXT_MIN_RATIO)) {
    console.error('[calibrate] BROKEN: known-good pair did not pass. Colour math is wrong.');
    return false;
  }
  console.log('[calibrate] OK — the gate genuinely discriminates.\n');
  return true;
}

// ---------------------------------------------------------------------------
// 2. Dev server + browser plumbing
// ---------------------------------------------------------------------------
function startVite(port: number): Promise<ChildProcess> {
  return new Promise((resolve, reject) => {
    const child = spawn('bun', ['x', 'vite', '--port', String(port), '--strictPort', '--host', '127.0.0.1'], {
      cwd: FRONTEND_DIR,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const timer = setTimeout(() => reject(new Error('vite dev server did not start in time')), 90000);
    const onData = (): void => {
      // Poll the probe URL; first hit warms the vite transform pipeline.
      void pollProbe(port).then((ok) => {
        if (ok) {
          clearTimeout(timer);
          resolve(child);
        }
      });
    };
    child.stdout?.on('data', onData);
    child.stderr?.on('data', onData);
    child.on('error', (e: Error) => {
      clearTimeout(timer);
      reject(e);
    });
    // Kick off polling even before vite prints anything.
    void pollProbe(port).then((ok) => {
      if (ok) {
        clearTimeout(timer);
        resolve(child);
      }
    });
  });
}

async function pollProbe(port: number, tries = 60): Promise<boolean> {
  for (let i = 0; i < tries; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}${PROBE_PATH}`);
      if (res.ok) return true;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
}

async function launchBrowser(): Promise<Browser> {
  const opts = { headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] };
  try {
    return await chromium.launch(opts);
  } catch (e) {
    const fallback = process.env['CHROME_PATH'] ?? '/usr/bin/chromium';
    console.log(`[browser] default launch failed (${(e as Error).message}); trying ${fallback}`);
    return await chromium.launch({ ...opts, executablePath: fallback });
  }
}

// ---------------------------------------------------------------------------
// 3. Tooltip activation (robust headless approach)
// ---------------------------------------------------------------------------
/** Is there a visible, SUBSTANTIVE tooltip inside this tab section?
 *
 * "Substantive" deliberately excludes the Recharts default tooltip rendering
 * a label with an EMPTY payload: that state contains no item rows, so a gate
 * that accepted it would PASS a tooltip whose item text (the reported bug
 * lives there) was never even sampled. Custom tooltips return null when
 * inactive, so any non-empty custom tooltip already carries its rows.
 */
async function visibleTooltipCount(
  page: Page,
  tabKey: string,
): Promise<number> {
  return page.evaluate((key) => {
    const section = document.querySelector(`section[data-tab="${key}"]`);
    if (!section) return 0;
    let n = 0;
    section.querySelectorAll('.recharts-tooltip-wrapper').forEach((tw) => {
      const el = tw as HTMLElement;
      const text = (el.textContent ?? '').trim();
      if (!text) return;
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return;
      const isDefault = !!el.querySelector('.recharts-default-tooltip');
      if (isDefault && !el.querySelector('.recharts-tooltip-item')) return; // label-only: keep hunting
      n += 1;
    });
    return n;
  }, tabKey);
}

async function activateTooltips(
  page: Page,
  section: ElementHandle,
  tabKey: string,
): Promise<string[]> {
  const notes: string[] = [];
  const wrappers = await section.$$('.recharts-wrapper');
  if (wrappers.length === 0) {
    notes.push('no .recharts-wrapper found in section');
    return notes;
  }
  for (let wi = 0; wi < wrappers.length; wi++) {
    const w = wrappers[wi];
    if (await visibleTooltipCount(page, tabKey) > 0) break;
    // Scroll the CHART (not the section) into view: tall sections can leave
    // the chart off-viewport, where mouse events silently hit nothing.
    await w.evaluate((el) => (el as HTMLElement).scrollIntoView({ block: 'center' }));
    await page.waitForTimeout(300);
    let box = await w.boundingBox();
    if (!box || box.y < 0 || box.y > 900) {
      await w.scrollIntoViewIfNeeded();
      await page.waitForTimeout(300);
      box = await w.boundingBox();
    }
    // Prefer real bar geometry when present (bar charts), else sweep points.
    let points: Array<{ x: number; y: number }> = [];
    try {
      const bars = await w.$$('.recharts-bar-rectangle path, .recharts-bar-rectangle');
      for (const b of bars.slice(0, 3)) {
        const bb = await b.boundingBox();
        if (bb && bb.width > 0 && bb.height > 0) points.push({ x: bb.x + bb.width / 2, y: bb.y + bb.height / 2 });
      }
    } catch {
      /* fall through to sweep */
    }
    if (box) {
      for (const fx of [0.3, 0.5, 0.7]) {
        for (const fy of [0.35, 0.55]) points.push({ x: box.x + box.width * fx, y: box.y + box.height * fy });
      }
    }
    // Two passes: Recharts animates bars/lines in on mount (~1.5s), and a
    // hover that lands mid-animation can yield an empty payload. The second
    // pass runs after everything has settled.
    let activated = false;
    for (let attempt = 0; attempt < 2 && !activated; attempt++) {
      if (attempt > 0) {
        await page.waitForTimeout(2500);
        // Re-resolve geometry post-animation (bar rects grow from zero).
        points = [];
        try {
          const bars = await w.$$('.recharts-bar-rectangle path, .recharts-bar-rectangle');
          for (const b of bars.slice(0, 3)) {
            const bb = await b.boundingBox();
            if (bb && bb.width > 0 && bb.height > 0) points.push({ x: bb.x + bb.width / 2, y: bb.y + bb.height / 2 });
          }
        } catch {
          /* fall through to sweep */
        }
        if (box) {
          for (const fx of [0.3, 0.5, 0.7]) {
            for (const fy of [0.35, 0.55]) points.push({ x: box.x + box.width * fx, y: box.y + box.height * fy });
          }
        }
      }
      for (const pt of points) {
        await page.mouse.move(pt.x, pt.y, { steps: 6 });
        await page.waitForTimeout(250);
        if ((await visibleTooltipCount(page, tabKey)) > 0) {
          activated = true;
          break;
        }
      }
    }
    if (!activated) {
      // Fallback: synthetic mouse events straight at the wrapper (headless
      // hover/CSS-hit-testing can be flaky; Recharts listens to React
      // synthetic mouse events, which dispatched events still trigger).
      notes.push(`chart #${wi}: mouse sweep missed; trying synthetic events`);
      // Diagnostic: distinguish "chart renders nothing" (component bug —
      // report, don't fix) from "hover didn't land" (checker problem).
      const domStats: string = await w.evaluate((el) => {
        const q = (s: string): number => el.querySelectorAll(s).length;
        return (
          `bars=${q('.recharts-bar-rectangle')} ` +
          `paths=${q('path.recharts-bar-rectangle, .recharts-area-curve, .recharts-line-curve')} ` +
          `dots=${q('.recharts-dot')} xticks=${q('.recharts-xAxis .recharts-cartesian-axis-tick')}`
        );
      });
      notes.push(`chart #${wi}: DOM contents: ${domStats}`);
      await w.evaluate((el) => {
        const r = (el as HTMLElement).getBoundingClientRect();
        const cx = r.left + r.width / 2;
        const cy = r.top + r.height / 2;
        for (const type of ['mouseenter', 'mouseover', 'mousemove']) {
          el.dispatchEvent(
            new MouseEvent(type, { bubbles: true, cancelable: true, clientX: cx, clientY: cy }),
          );
        }
      });
      await page.waitForTimeout(400);
      if ((await visibleTooltipCount(page, tabKey)) > 0) activated = true;
      else notes.push(`chart #${wi}: tooltip did not activate`);
    }
  }
  return notes;
}

// ---------------------------------------------------------------------------
// 4. Measurement: computed colours straight from Chromium
// ---------------------------------------------------------------------------
async function measureTab(page: Page, tabKey: string): Promise<{ tooltips: TooltipMeasurement[]; chrome: ChromeSample[] }> {
  return page.evaluate(
    ({ key, explicit }: { key: string; explicit: string[] }) => {
      function parseRgba(s: string): { r: number; g: number; b: number; a: number } | null {
        const m = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)$/.exec(
          s.trim().toLowerCase(),
        );
        if (!m) return null;
        return { r: Number(m[1]), g: Number(m[2]), b: Number(m[3]), a: m[4] === undefined ? 1 : Number(m[4]) };
      }
      function describe(el: Element): string {
        const h = el as HTMLElement;
        const cls = (h.className && typeof h.className === 'string' ? h.className : '')
          .split(/\s+/)
          .filter((c) => c && !c.startsWith('recharts-'))
          .slice(0, 3)
          .join('.');
        return `<${el.tagName.toLowerCase()}${cls ? '.' + cls : ''}>`;
      }
      const section = document.querySelector(`section[data-tab="${key}"]`);
      if (!section) return { tooltips: [], chrome: [] };
      const out: TooltipMeasurement[] = [];
      const chrome: ChromeSample[] = [];
      function effectiveBg(el: Element): { bg: string; desc: string } | null {
        let node: HTMLElement | null = el as HTMLElement;
        for (let d = 0; d < 10 && node; d++) {
          const b = getComputedStyle(node).backgroundColor;
          const p = parseRgba(b);
          if (p && p.a >= 1) return { bg: b, desc: describe(node) };
          node = node.parentElement;
        }
        return null;
      }
      section.querySelectorAll('.recharts-tooltip-wrapper').forEach((tw) => {
        const wrap = tw as HTMLElement;
        if (!((wrap.textContent ?? '').trim())) return; // inactive tooltip
        const wr = wrap.getBoundingClientRect();
        if (wr.width === 0 && wr.height === 0) return;
        const isDefault = !!wrap.querySelector('.recharts-default-tooltip');
        if (isDefault && !wrap.querySelector('.recharts-tooltip-item')) return; // label-only: not scoreable
        const content = wrap.firstElementChild as HTMLElement | null;
        if (!content) return;
        // Effective surface: nearest ancestor (incl. self) with opaque bg.
        let bgNode: HTMLElement | null = content;
        let surfaceBg = '';
        let surfaceDesc = describe(content);
        let node: HTMLElement | null = content;
        for (let d = 0; d < 8 && node; d++) {
          const b = getComputedStyle(node).backgroundColor;
          const p = parseRgba(b);
          if (p && p.a >= 1 && !(p.r === 0 && p.g === 0 && p.b === 0 && p.a === 0)) {
            surfaceBg = b;
            surfaceDesc = describe(node);
            bgNode = node;
            break;
          }
          node = node.parentElement;
        }
        if (!surfaceBg || !bgNode) return;
        void bgNode;
        const texts: TextSample[] = [];
        const seen = new Set<string>();
        // Leaf text nodes: the actual rendered strings and their colours.
        const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
        let t: Node | null = walker.nextNode();
        while (t) {
          const raw = (t.nodeValue ?? '').replace(/\s+/g, ' ').trim();
          const parent = t.parentElement;
          if (raw && parent) {
            const pr = parent.getBoundingClientRect();
            const cs = getComputedStyle(parent);
            if (pr.width > 0 && pr.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none') {
              const key2 = `${cs.color}|${raw.slice(0, 48)}`;
              if (!seen.has(key2)) {
                seen.add(key2);
                texts.push({
                  desc: `text ${describe(parent)}`,
                  color: cs.color,
                  fontPx: parseFloat(cs.fontSize) || 12,
                  fontWeight: Number(cs.fontWeight) || 400,
                  sample: raw.slice(0, 60),
                });
              }
            }
          }
          t = walker.nextNode();
        }
        // Explicit Recharts default-tooltip selectors (the reported bug).
        for (const sel of explicit) {
          content.querySelectorAll(sel).forEach((n) => {
            const h = n as HTMLElement;
            const r = h.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) return;
            const cs = getComputedStyle(h);
            const raw = ((h.textContent ?? '').replace(/\s+/g, ' ').trim()).slice(0, 60);
            const key2 = `${sel}|${cs.color}`;
            if (!seen.has(key2)) {
              seen.add(key2);
              texts.push({
                desc: `selector \`${sel}\``,
                color: cs.color,
                fontPx: parseFloat(cs.fontSize) || 12,
                fontWeight: Number(cs.fontWeight) || 400,
                sample: raw,
              });
            }
          });
        }
        out.push({ surfaceDesc, surfaceBg, texts });
      });
      // Chart chrome: axis tick labels + legend entries. These inherit their
      // colour (telemetry/arbitrage ticks resolve to #737373 via the axis
      // stroke) so they are sampled here from computed style — the same bug
      // class as tooltip text, one DOM level up.
      const pushChrome = (el: Element, kind: string): void => {
        const h = el as HTMLElement;
        const r = h.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) return;
        const cs = getComputedStyle(h);
        // SVG <text> paints via `fill`, HTML legend text via `color`.
        const painted = (cs as unknown as { fill?: string }).fill && h.tagName.toLowerCase() === 'text'
          ? (cs as unknown as { fill: string }).fill
          : cs.color;
        const raw = ((h.textContent ?? '').replace(/\s+/g, ' ').trim()).slice(0, 40);
        if (!raw) return;
        const surf = effectiveBg(h);
        if (!surf) return;
        chrome.push({
          desc: `${kind} "${raw}"`,
          color: painted,
          fontPx: parseFloat(cs.fontSize) || 11,
          fontWeight: Number(cs.fontWeight) || 400,
          sample: raw,
          surfaceBg: surf.bg,
          surfaceDesc: surf.desc,
        });
      };
      section.querySelectorAll('.recharts-cartesian-axis-tick text').forEach((t, i) => {
        if (i < 8) pushChrome(t, 'axis tick');
      });
      section.querySelectorAll('.recharts-legend-item-text').forEach((t) => pushChrome(t, 'legend'));
      return { tooltips: out, chrome };
    },
    { key: tabKey, explicit: EXPLICIT_SELECTORS },
  );
}

// ---------------------------------------------------------------------------
// 5. Main
// ---------------------------------------------------------------------------
async function main(): Promise<number> {
  console.log('=== APIx tooltip contrast gate (WCAG 2.1 AA: 4.5:1 normal, 3:1 large) ===\n');
  if (!calibrate()) return 2;

  const portArg = process.argv.indexOf('--port');
  const port =
    portArg >= 0 && process.argv[portArg + 1]
      ? Number(process.argv[portArg + 1])
      : Number(process.env['CONTRAST_PROBE_PORT'] ?? 5199);

  console.log(`[server] starting vite dev on :${port} ...`);
  let vite: ChildProcess | null = null;
  let browser: Browser | null = null;
  try {
    vite = await startVite(port);
  } catch (e) {
    console.error(`[server] FAILED to start vite: ${(e as Error).message}`);
    return 2;
  }
  console.log('[server] up.\n');

  try {
    browser = await launchBrowser();
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    await page.goto(`http://127.0.0.1:${port}${PROBE_PATH}`, { waitUntil: 'load' });
    // At least one chart must render; per-tab vacuous-guards below handle the
    // rest (a tab with no activatable tooltip FAILS, it never passes silently).
    await page.waitForFunction(
      () => document.querySelectorAll('.recharts-wrapper').length >= 1,
      null,
      { timeout: 45000 },
    );
    // Let charts settle (animations) so tooltips anchor correctly.
    await page.waitForTimeout(1500);

    const results: TabResult[] = [];
    for (const tab of TABS) {
      const res: TabResult = { key: tab.key, title: tab.title, activated: 0, checks: [], errors: [], pass: true };
      const section = await page.$(`section[data-tab="${tab.key}"]`);
      if (!section) {
        res.errors.push('probe section missing from page');
        res.pass = false;
        results.push(res);
        continue;
      }
      // Hidden sections (e.g. the negative control's placeholders) carry no
      // charts; that is an error for that tab, never a pass.
      if (!(await section.isVisible())) {
        res.errors.push('section not visible — no charts to check (vacuous result rejected)');
        res.pass = false;
        results.push(res);
        continue;
      }
      const chartCount = await section.$$('.recharts-wrapper').then((els) => els.length);
      if (chartCount === 0) {
        res.errors.push('section has no .recharts-wrapper charts (vacuous result rejected)');
        res.pass = false;
        results.push(res);
        continue;
      }
      // Scroll into view — Recharts measures on mouse position; offscreen
      // charts misbehave headless.
      await section.scrollIntoViewIfNeeded();
      await page.waitForTimeout(300);
      const notes = await activateTooltips(page, section, tab.key);
      const { tooltips: measurements, chrome: chromeSamples } = await measureTab(page, tab.key);
      res.activated = measurements.length;
      for (const c of chromeSamples) {
        const fgParsed = parseColor(c.color);
        const bgParsed = parseColor(c.surfaceBg);
        if (!fgParsed || !bgParsed) {
          res.errors.push(`chart chrome ${c.desc}: unparseable colours "${c.color}" / "${c.surfaceBg}"`);
          res.pass = false;
          continue;
        }
        const bg = { ...bgParsed, a: 1 };
        const fg = fgParsed.a < 1 ? compositeOver(fgParsed, bg) : { ...fgParsed, a: 1 };
        const ratio = contrastRatio(fg, bg);
        const threshold = thresholdFor(c.fontPx, c.fontWeight);
        const pass = ratio >= threshold;
        res.checks.push({
          tooltip: `chart chrome (${c.surfaceDesc} ${c.surfaceBg})`,
          desc: `${c.desc} [${c.fontPx}px${c.fontWeight >= 700 ? '/bold' : ''}]`,
          fg: c.color,
          bg: c.surfaceBg,
          ratio,
          threshold,
          pass,
        });
        if (!pass) res.pass = false;
      }
      if (measurements.length === 0) {
        res.errors.push('NO tooltip could be activated (vacuous result rejected)');
        for (const n of notes) res.errors.push('activate: ' + n);
        res.pass = false;
        results.push(res);
        continue;
      }
      for (let ti = 0; ti < measurements.length; ti++) {
        const m = measurements[ti];
        const bgParsed = parseColor(m.surfaceBg);
        if (!bgParsed) {
          res.errors.push(`tooltip #${ti}: unparseable surface bg "${m.surfaceBg}"`);
          res.pass = false;
          continue;
        }
        const bg = { ...bgParsed, a: 1 };
        if (m.texts.length === 0) {
          res.errors.push(`tooltip #${ti}: surface found but zero text nodes (vacuous result rejected)`);
          res.pass = false;
          continue;
        }
        for (const txt of m.texts) {
          const fgParsed = parseColor(txt.color);
          if (!fgParsed) {
            res.errors.push(`tooltip #${ti} ${txt.desc}: unparseable fg "${txt.color}"`);
            res.pass = false;
            continue;
          }
          const fg = fgParsed.a < 1 ? compositeOver(fgParsed, bg) : { ...fgParsed, a: 1 };
          const ratio = contrastRatio(fg, bg);
          const threshold = thresholdFor(txt.fontPx, txt.fontWeight);
          const pass = ratio >= threshold;
          res.checks.push({
            tooltip: `tooltip #${ti} (${m.surfaceDesc} ${m.surfaceBg})`,
            desc: `${txt.desc} "${txt.sample}" [${txt.fontPx}px${txt.fontWeight >= 700 ? '/bold' : ''}]`,
            fg: txt.color,
            bg: m.surfaceBg,
            ratio,
            threshold,
            pass,
          });
          if (!pass) res.pass = false;
        }
      }
      results.push(res);
    }

    // ---- report ----
    let fails = 0;
    console.log('---------------- TAB RESULTS ----------------');
    for (const r of results) {
      const worst = r.checks.length ? Math.min(...r.checks.map((c) => c.ratio)) : NaN;
      console.log(`\nTAB ${r.key} — ${r.title}: ${r.pass ? 'PASS' : 'FAIL'} ` +
        `(tooltips: ${r.activated}, checks: ${r.checks.length}` +
        (r.checks.length ? `, worst: ${fmtRatio(worst)}` : '') + ')');
      const byTooltip = new Map<string, typeof r.checks>();
      for (const c of r.checks) {
        const arr = byTooltip.get(c.tooltip) ?? [];
        arr.push(c);
        byTooltip.set(c.tooltip, arr);
      }
      for (const [tip, cs] of byTooltip) {
        console.log(`  ${tip}:`);
        for (const c of cs) {
          console.log(`    [${c.pass ? 'PASS' : 'FAIL'}] ${c.desc}`);
          console.log(`           fg ${c.fg} on ${c.bg} = ${fmtRatio(c.ratio)} (needs ${c.threshold}:1)`);
        }
      }
      for (const e of r.errors) {
        console.log(`  [ERROR] ${e}`);
        fails += 1;
      }
      if (!r.pass) fails += 1;
    }
    const passed = results.filter((r) => r.pass).length;
    console.log('\n================ SUMMARY ================');
    console.log(`${passed}/${results.length} tabs pass.`);
    for (const r of results) console.log(`  ${r.pass ? 'PASS' : 'FAIL'}  ${r.key} (${r.title})`);
    if (fails > 0) {
      console.log('\nCONTRAST GATE: FAIL — dark-theme text below WCAG AA. Exit 1.');
      return 1;
    }
    console.log('\nCONTRAST GATE: PASS. Exit 0.');
    return 0;
  } catch (e) {
    console.error(`[checker] INFRA FAILURE: ${(e as Error).stack ?? (e as Error).message}`);
    return 2;
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (vite) vite.kill('SIGTERM');
  }
}

const code = await main();
process.exit(code);
