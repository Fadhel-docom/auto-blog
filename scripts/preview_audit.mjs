// Preview audit: renders the site in a real browser (Playwright/Chromium) and
// measures layout, contrast and tap targets. It compares a locally built preview
// (Hugo build of the PR) against the live site. Read-only: no deploy, no AI API,
// no writes to the repository. Third-party requests (analytics) are blocked so
// the audit never pollutes traffic statistics.
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const norm = u => u.replace(/\/?$/, "/");
const PREVIEW = norm(process.env.PREVIEW_URL || "http://127.0.0.1:8080/auto-blog/");
const LIVE = process.env.LIVE_URL ? norm(process.env.LIVE_URL) : "";
const OUT = path.resolve("artifacts");
fs.mkdirSync(OUT, { recursive: true });

const VIEWPORTS = [
  { id: "m360", width: 360, height: 740, mobile: true },
  { id: "m390", width: 390, height: 844, mobile: true },
  { id: "t768", width: 768, height: 1024, mobile: false },
  { id: "d1440", width: 1440, height: 900, mobile: false },
];
const SCHEMES = ["light", "dark"];

// Runs inside the page. Returns plain JSON.
function measure() {
  const vw = window.innerWidth;
  const q = s => document.querySelector(s);
  const qa = s => [...document.querySelectorAll(s)];
  const parse = c => {
    const m = (c || "").match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const lin = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const lum = c => 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b);
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const over = (top, bottom) => {
    const a = top.a + bottom.a * (1 - top.a);
    if (a === 0) return { r: 255, g: 255, b: 255, a: 0 };
    const f = (t, b) => (t * top.a + b * bottom.a * (1 - top.a)) / a;
    return { r: f(top.r, bottom.r), g: f(top.g, bottom.g), b: f(top.b, bottom.b), a };
  };
  // Effective background; null when the text sits on an image/gradient (not measurable).
  const background = el => {
    const layers = [];
    for (let n = el; n; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.backgroundImage && cs.backgroundImage !== "none") return null;
      const c = parse(cs.backgroundColor);
      if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; }
    }
    let base = { r: 255, g: 255, b: 255, a: 1 };
    for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base);
    return base;
  };
  const opacityOf = el => { let o = 1; for (let n = el; n; n = n.parentElement) o *= parseFloat(getComputedStyle(n).opacity || "1"); return o; };

  const fails = new Map();
  let checked = 0, skippedImage = 0;
  const textEls = qa("body *").filter(el => {
    if (["SCRIPT", "STYLE", "SVG", "PATH", "NOSCRIPT"].includes(el.tagName.toUpperCase())) return false;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 1);
    if (!own) return false;
    if (el.closest(".home-hero-image-caption")) return false; // text over a photo + pseudo-element gradient: not measurable
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
  });
  for (const el of textEls) {
    const cs = getComputedStyle(el);
    const fg = parse(cs.color);
    const bg = background(el);
    if (!fg) continue;
    if (!bg) { skippedImage++; continue; }
    const fgEff = over({ ...fg, a: fg.a * opacityOf(el) }, bg);
    const r = ratio(fgEff, bg);
    const size = parseFloat(cs.fontSize);
    const bold = parseInt(cs.fontWeight, 10) >= 700;
    const large = size >= 24 || (size >= 18.66 && bold);
    const need = large ? 3 : 4.5;
    checked++;
    if (r < need) {
      const key = el.tagName.toLowerCase() + (el.className && typeof el.className === "string" && el.className.trim() ? "." + el.className.trim().split(/\s+/)[0] : "");
      const prev = fails.get(key) || { count: 0, worst: 99, sample: "", need };
      prev.count++;
      if (r < prev.worst) { prev.worst = r; prev.sample = el.textContent.trim().slice(0, 40); prev.need = need; }
      fails.set(key, prev);
    }
  }
  const contrastFails = [...fails.entries()].map(([k, v]) => ({ selector: k, count: v.count, worst: Math.round(v.worst * 100) / 100, need: v.need, sample: v.sample })).sort((a, b) => b.count - a.count).slice(0, 12);

  const gutters = {};
  for (const s of [".home-hero-editorial", ".home-search", ".featured-section", ".home-posts", ".home-rooms", ".site-footer"]) {
    const el = q(s);
    if (el) { const r = el.getBoundingClientRect(); gutters[s] = { left: Math.round(r.left), right: Math.round(vw - r.right), width: Math.round(r.width) }; }
  }
  const hero = q(".home-hero-editorial"), heroImg = q(".home-hero-image");
  const heroInfo = hero && heroImg ? {
    imageOffsetLeft: Math.round(heroImg.getBoundingClientRect().left - hero.getBoundingClientRect().left),
    imageOffsetTop: Math.round(heroImg.getBoundingClientRect().top - hero.getBoundingClientRect().top),
    heroHeight: Math.round(hero.getBoundingClientRect().height),
  } : null;
  const search = q("#post-search");
  const chips = qa(".home-search .category-filter");
  const tops = [...new Set(chips.map(c => Math.round(c.getBoundingClientRect().top)))];
  const chipInfo = chips.length ? {
    count: chips.length, rows: tops.length,
    maxRight: Math.max(...chips.map(c => Math.round(c.getBoundingClientRect().right))),
    maxHeight: Math.max(...chips.map(c => Math.round(c.getBoundingClientRect().height))),
    searchWidth: search ? Math.round(search.getBoundingClientRect().width) : null,
  } : null;
  const feats = qa(".featured-card").map(c => ({ h: Math.round(c.getBoundingClientRect().height), primary: c.classList.contains("featured-card-primary") }));
  const meta = q(".home-posts .home-post-card-meta");
  const metaInfo = meta ? { direction: getComputedStyle(meta).flexDirection, height: Math.round(meta.getBoundingClientRect().height) } : null;
  const tapSmall = qa("header a, header button, .site-nav a, .category-filter, .home-room-card, .home-hero-button").filter(e => {
    const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (r.height < 44 || r.width < 44);
  }).length;
  const categoryLinks = qa('a[href*="/categories/"]').length;
  const footerRooms = qa(".site-footer-rooms a").length;
  const cards = qa(".home-post-card").length;
  const intro = q(".category-intro") ? q(".category-intro").textContent.trim().length : 0;
  const brokenImages = qa("img").filter(i => i.complete && i.naturalWidth === 0).length;
  const missingAnchors = [...new Set(qa('a[href^="#"]').map(a => a.getAttribute("href")).filter(h => h && h.length > 1 && !document.getElementById(decodeURIComponent(h.slice(1)))))];
  const rs = getComputedStyle(document.documentElement);
  const tokens = { accent: rs.getPropertyValue("--accent").trim(), muted: rs.getPropertyValue("--muted").trim(), bodyBg: getComputedStyle(document.body).backgroundColor, bodyColor: getComputedStyle(document.body).color };
  return {
    viewport: vw, docWidth: document.documentElement.scrollWidth,
    overflowX: document.documentElement.scrollWidth > vw + 1, docHeight: document.documentElement.scrollHeight,
    h1: q("h1") ? q("h1").textContent.trim().slice(0, 70) : null,
    gutters, heroInfo, chipInfo, feats, metaInfo, tapSmall, brokenImages, missingAnchors, tokens,
    categoryLinks, footerRooms, cards, intro,
    contrast: { checked, skippedOnImages: skippedImage, failing: contrastFails },
  };
}

async function discover(base) {
  const html = await (await fetch(base)).text();
  const post = (html.match(/href=["']?([^"'\s>]*\/posts\/[^"'\s>#?]+\/)/i) || [])[1];
  const cat = (html.match(/href=["']?([^"'\s>]*\/categories\/[a-z0-9-]+\/)/i) || [])[1];
  const abs = p => (p ? new URL(p, base).href : null);
  return { home: base, post: abs(post), category: abs(cat) || new URL("categories/kitchen/", base).href };
}

async function audit(label, base, browser) {
  const pages = await discover(base);
  const origin = new URL(base).origin;
  const results = [];
  for (const vp of VIEWPORTS) {
    for (const scheme of SCHEMES) {
      const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, isMobile: vp.mobile, hasTouch: vp.mobile, colorScheme: scheme, deviceScaleFactor: 1 });
      await ctx.route("**/*", route => { const u = route.request().url(); return u.startsWith(origin) || u.startsWith("data:") ? route.continue() : route.abort(); });
      for (const [pname, url] of Object.entries(pages)) {
        if (!url) continue;
        if (scheme === "dark" && pname !== "home") continue;
        const page = await ctx.newPage();
        const errors = [];
        page.on("pageerror", e => errors.push(e.message.slice(0, 200)));
        const entry = { label, page: pname, viewport: vp.id, scheme, url };
        try {
          const resp = await page.goto(url, { waitUntil: "networkidle", timeout: 60000 });
          entry.status = resp ? resp.status() : null;
          await page.waitForTimeout(500);
          entry.metrics = await page.evaluate(measure);
          entry.errors = errors;
          const wantShot = (pname === "home" && ["m390", "d1440"].includes(vp.id)) || (pname !== "home" && vp.id === "m390" && scheme === "light");
          if (wantShot) {
            const shot = `${label}-${pname}-${vp.id}-${scheme}.jpg`;
            await page.screenshot({ path: path.join(OUT, shot), type: "jpeg", quality: 55, fullPage: true, animations: "disabled" });
            entry.screenshot = shot;
          }
        } catch (e) { entry.error = String(e.message || e).slice(0, 300); }
        results.push(entry);
        await page.close();
      }
      await ctx.close();
    }
  }
  return { base, pages, results };
}

const browser = await chromium.launch({ headless: true });
const report = { generated: new Date().toISOString(), preview: null, live: null };
report.preview = await audit("preview", PREVIEW, browser);
if (LIVE) { try { report.live = await audit("live", LIVE, browser); } catch (e) { report.live = { error: String(e.message || e) }; } }
await browser.close();

const find = (rep, page, vp, scheme = "light") => (rep && rep.results ? rep.results.find(r => r.page === page && r.viewport === vp && r.scheme === scheme) : null);
const mm = r => (r && r.metrics) || null;
const cell = v => (v === undefined || v === null ? "n/a" : String(v));
const lines = ["# Preview audit (real browser, local Hugo build)", "",
  `Preview: \`${PREVIEW}\`${LIVE ? ` - compared with live \`${LIVE}\`` : ""}`, "",
  "Measured in Chromium; this is not a human visual review. Third-party requests are blocked.", ""];

const failures = [];
for (const r of report.preview.results) {
  const id = `${r.page}/${r.viewport}/${r.scheme}`;
  if (r.error) failures.push(`${id}: ${r.error}`);
  else if (r.status !== 200) failures.push(`${id}: HTTP ${r.status}`);
  else {
    if (r.metrics.overflowX) failures.push(`${id}: horizontal overflow (${r.metrics.docWidth}px > ${r.metrics.viewport}px)`);
    if (r.metrics.brokenImages) failures.push(`${id}: ${r.metrics.brokenImages} broken image(s)`);
    if (r.metrics.missingAnchors.length) failures.push(`${id}: missing anchor target(s) ${r.metrics.missingAnchors.join(", ")}`);
    if (r.errors && r.errors.length) failures.push(`${id}: ${r.errors.length} page error(s)`);
  }
}
lines.push("## Findings", "", ...(failures.length ? failures.map(f => `- ${f}`) : ["- No HTTP, overflow, broken-image, anchor or page-error findings."]), "");

lines.push("## Home layout: preview vs live", "", "| Check | Viewport | Preview | Live |", "|---|---|---|---|");
const g = (x, s, k) => (x && x.gutters && x.gutters[s] ? x.gutters[s][k] : null);
const chip = x => (x && x.chipInfo ? `${x.chipInfo.rows} rows / right ${x.chipInfo.maxRight} / h ${x.chipInfo.maxHeight}` : "n/a");
const hero = x => (x && x.heroInfo ? `${x.heroInfo.imageOffsetLeft}/${x.heroInfo.imageOffsetTop}` : "n/a");
const fh = x => (x && x.feats && x.feats.length ? x.feats.map(f => f.h).join(",") : "n/a");
for (const vp of ["m360", "m390", "d1440"]) {
  const p = mm(find(report.preview, "home", vp)), l = mm(find(report.live, "home", vp));
  if (!p) continue;
  lines.push(`| featured section gutter left/right (px) | ${vp} | ${cell(g(p, ".featured-section", "left"))}/${cell(g(p, ".featured-section", "right"))} | ${cell(g(l, ".featured-section", "left"))}/${cell(g(l, ".featured-section", "right"))} |`);
  lines.push(`| latest grid gutter left/right (px) | ${vp} | ${cell(g(p, ".home-posts", "left"))}/${cell(g(p, ".home-posts", "right"))} | ${cell(g(l, ".home-posts", "left"))}/${cell(g(l, ".home-posts", "right"))} |`);
  lines.push(`| search input width (px) | ${vp} | ${cell(p.chipInfo && p.chipInfo.searchWidth)} | ${cell(l && l.chipInfo && l.chipInfo.searchWidth)} |`);
  lines.push(`| category chips | ${vp} | ${chip(p)} | ${chip(l)} |`);
  lines.push(`| hero photo offset left/top (px) | ${vp} | ${hero(p)} | ${hero(l)} |`);
  lines.push(`| featured card heights (px) | ${vp} | ${fh(p)} | ${fh(l)} |`);
  lines.push(`| document height (px) | ${vp} | ${cell(p.docHeight)} | ${cell(l && l.docHeight)} |`);
  lines.push(`| small tap targets (<44px) | ${vp} | ${cell(p.tapSmall)} | ${cell(l && l.tapSmall)} |`);
}
lines.push("");

lines.push("## Category discovery and category pages", "", "| Page | Viewport | Category links on page (preview/live) | Footer room links (preview/live) | Post cards (preview/live) | Intro chars (preview/live) |", "|---|---|---|---|---|---|");
for (const pg of ["home", "category", "post"]) {
  for (const vp of ["m390", "d1440"]) {
    const p = mm(find(report.preview, pg, vp)), l = mm(find(report.live, pg, vp));
    if (!p) continue;
    lines.push(`| ${pg} | ${vp} | ${cell(p.categoryLinks)}/${cell(l && l.categoryLinks)} | ${cell(p.footerRooms)}/${cell(l && l.footerRooms)} | ${cell(p.cards)}/${cell(l && l.cards)} | ${cell(p.intro)}/${cell(l && l.intro)} |`);
  }
}
lines.push("");

lines.push("## Contrast (WCAG AA) on rendered text", "", "Text over images or gradients is skipped (not measurable here).", "", "| Page | Viewport | Scheme | Checked | Failing groups (preview) | Failing groups (live) |", "|---|---|---|---|---|---|");
for (const r of report.preview.results) {
  if (!r.metrics || !["m390", "d1440"].includes(r.viewport)) continue;
  const l = mm(find(report.live, r.page, r.viewport, r.scheme));
  lines.push(`| ${r.page} | ${r.viewport} | ${r.scheme} | ${r.metrics.contrast.checked} | ${r.metrics.contrast.failing.length} | ${l ? l.contrast.failing.length : "n/a"} |`);
}
lines.push("");
for (const r of report.preview.results.filter(x => x.metrics && x.metrics.contrast.failing.length && x.viewport === "m390").slice(0, 4)) {
  lines.push(`### Failing text groups: ${r.page} ${r.viewport} ${r.scheme}`, "", "| Selector | Count | Worst ratio | Needed | Sample |", "|---|---|---|---|---|",
    ...r.metrics.contrast.failing.slice(0, 8).map(f => `| \`${f.selector}\` | ${f.count} | ${f.worst} | ${f.need} | ${f.sample.replace(/\|/g, " ")} |`), "");
}
const t = mm(find(report.preview, "home", "m390")), td = mm(find(report.preview, "home", "m390", "dark"));
if (t) lines.push("## Design tokens as rendered", "", `- light: --accent \`${t.tokens.accent}\`, --muted \`${t.tokens.muted}\`, body ${t.tokens.bodyColor} on ${t.tokens.bodyBg}`);
if (td) lines.push(`- dark: body ${td.tokens.bodyColor} on ${td.tokens.bodyBg}`);
lines.push("", "Screenshots are in the workflow artifact `homeorg-preview-audit`.", "");

fs.writeFileSync(path.join(OUT, "preview-report.md"), lines.join("\n").slice(0, 60000));
fs.writeFileSync(path.join(OUT, "preview-report.json"), JSON.stringify(report, null, 2));
console.log(lines.slice(0, 30).join("\n"));
