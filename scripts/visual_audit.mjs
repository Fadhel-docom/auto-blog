import fs from "node:fs";
import path from "node:path";
import { chromium, devices } from "playwright";

const SITE_URL = (process.env.SITE_URL || "https://fadhel-docom.github.io/auto-blog/").replace(/\/?$/, "/");
const OUT = path.resolve("artifacts");
fs.mkdirSync(OUT, { recursive: true });

const report = {
  timestamp: new Date().toISOString(),
  site: SITE_URL,
  note: "Rendered browser audit; this does not modify or deploy the site.",
  pages: [],
  browserErrors: [],
  failedRequests: [],
};

const browser = await chromium.launch({ headless: true });

async function inspectPage(label, url, viewport, deviceScaleFactor = 1, isMobile = false) {
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor,
    isMobile,
    hasTouch: isMobile,
    colorScheme: "light",
  });
  const page = await context.newPage();
  page.on("pageerror", error => report.browserErrors.push({ page: label, message: error.message }));
  page.on("console", message => {
    if (message.type() === "error") report.browserErrors.push({ page: label, message: message.text().slice(0, 300) });
  });
  page.on("requestfailed", request => {
    report.failedRequests.push({ page: label, url: request.url(), error: request.failure()?.errorText || "request failed" });
  });

  const entry = { label, url, viewport, status: null, title: "", h1: "", screenshot: null, horizontalOverflow: null, documentWidth: null, viewportWidth: viewport.width, images: { total: 0, loaded: 0 }, internalLinks: 0, externalLinks: 0, missingAnchors: [] };
  try {
    const response = await page.goto(url, { waitUntil: "networkidle", timeout: 45000 });
    entry.status = response?.status() ?? null;
    await page.waitForTimeout(700);
    entry.title = await page.title();
    entry.h1 = await page.locator("h1").first().textContent().catch(() => "");
    const metrics = await page.evaluate(() => {
      const images = [...document.images];
      const links = [...document.querySelectorAll("a[href]")];
      const anchors = [...document.querySelectorAll('a[href^="#"]')]
        .map(a => a.getAttribute("href"))
        .filter(href => href && href.length > 1)
        .filter(href => !document.getElementById(decodeURIComponent(href.slice(1))));
      return {
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
        imagesTotal: images.length,
        imagesLoaded: images.filter(img => img.complete && img.naturalWidth > 0).length,
        internalLinks: links.filter(a => new URL(a.href, location.href).origin === location.origin).length,
        externalLinks: links.filter(a => new URL(a.href, location.href).origin !== location.origin).length,
        missingAnchors: [...new Set(anchors)],
      };
    });
    entry.documentWidth = metrics.documentWidth;
    entry.horizontalOverflow = metrics.documentWidth > metrics.viewportWidth;
    entry.images = { total: metrics.imagesTotal, loaded: metrics.imagesLoaded };
    entry.internalLinks = metrics.internalLinks;
    entry.externalLinks = metrics.externalLinks;
    entry.missingAnchors = metrics.missingAnchors;
    const safeLabel = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    entry.screenshot = `artifacts/${safeLabel}.jpg`;
    await page.screenshot({ path: entry.screenshot, type: "jpeg", quality: 68, animations: "disabled" });
  } catch (error) {
    entry.error = error.message;
  }
  report.pages.push(entry);
  await context.close();
}

try {
  const homeResponse = await fetch(SITE_URL, { redirect: "follow" });
  const homeHtml = await homeResponse.text();
  const articleMatch = homeHtml.match(/href=["']([^"']*\/posts\/[^"'#?]+\/?)(?:["'])/i);
  let articleUrl = articleMatch ? new URL(articleMatch[1], SITE_URL).href : SITE_URL;
  if (articleUrl === SITE_URL) {
    const found = [...homeHtml.matchAll(/href=["']([^"']*\/posts\/[^"'#?]+\/?)(?:["'])/gi)][0];
    if (found) articleUrl = new URL(found[1], SITE_URL).href;
  }

  await inspectPage("home-desktop", SITE_URL, { width: 1440, height: 1000 });
  await inspectPage("home-mobile", SITE_URL, { width: 390, height: 844 }, 1, true);
  await inspectPage("article-desktop", articleUrl, { width: 1440, height: 1000 });
  await inspectPage("article-mobile", articleUrl, { width: 390, height: 844 }, 1, true);
} finally {
  await browser.close();
}

const failures = [];
for (const page of report.pages) {
  if (page.status !== 200) failures.push(`${page.label}: HTTP ${page.status ?? "unknown"}`);
  if (page.horizontalOverflow) failures.push(`${page.label}: horizontal overflow (${page.documentWidth}px document vs ${page.viewportWidth}px viewport)`);
  if (page.error) failures.push(`${page.label}: ${page.error}`);
  if (page.missingAnchors?.length) failures.push(`${page.label}: missing in-page targets: ${page.missingAnchors.join(", ")}`);
}
report.summary = {
  pagesChecked: report.pages.length,
  failures,
  browserErrorsCount: report.browserErrors.length,
  failedRequestsCount: report.failedRequests.length,
};
fs.writeFileSync(path.join(OUT, "visual-audit-report.json"), JSON.stringify(report, null, 2));

const lines = [
  "# HomeOrg visual audit",
  "",
  `- Captured: ${report.timestamp}`,
  `- Target: ${SITE_URL}`,
  "- Method: Playwright Chromium, real DOM/CSS rendering; no AI API called and no site changes made.",
  "- Viewports: desktop 1440×1000 and mobile 390×844; homepage and one discovered article.",
  "",
  "## Results",
  "",
  `- Pages checked: ${report.summary.pagesChecked}`,
  `- Findings: ${failures.length}`,
  `- Browser/console errors: ${report.browserErrors.length}`,
  `- Failed requests: ${report.failedRequests.length}`,
  "",
  ...report.pages.flatMap(p => [
    `### ${p.label}`,
    `- URL: ${p.url}`,
    `- HTTP: ${p.status ?? "unknown"}`,
    `- Title/H1: ${p.title || "(missing title)"} / ${(p.h1 || "").trim() || "(missing H1)"}`,
    `- Horizontal overflow: ${p.horizontalOverflow === null ? "not measured" : p.horizontalOverflow ? "YES" : "no"}`,
    `- Images loaded: ${p.images.loaded}/${p.images.total}`,
    `- Links: ${p.internalLinks} internal, ${p.externalLinks} external`,
    `- Screenshot: ${p.screenshot || "not captured"}`,
    ...(p.error ? [`- Error: ${p.error}`] : []),
    ...(p.missingAnchors?.length ? [`- Missing anchor targets: ${p.missingAnchors.join(", ")}`] : []),
    "",
  ]),
  "## Findings requiring review",
  "",
  ...(failures.length ? failures.map(f => `- ${f}`) : ["- No basic status/overflow/anchor failures detected. This is not proof of full visual correctness."]),
  "",
  "## Browser errors",
  "",
  ...(report.browserErrors.length ? report.browserErrors.slice(0, 30).map(e => `- [${e.page}] ${e.message}`) : ["- None captured."]),
  "",
  "## Failed requests",
  "",
  ...(report.failedRequests.length ? report.failedRequests.slice(0, 30).map(e => `- [${e.page}] ${e.url} — ${e.error}`) : ["- None captured."]),
  "",
  "Screenshots are attached to this workflow run as the `homeorg-visual-eyes` artifact (7-day retention). The report is evidence for review, not an automatic approval or deployment.",
];
fs.writeFileSync(path.join(OUT, "visual-audit-report.md"), lines.join("\n"));
console.log(lines.join("\n"));
