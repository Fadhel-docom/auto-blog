# Indexing Incident — 2026-10-27

## Scope and safety
- Project: Home Organization Ideas (Fadhel-docom/auto-blog).
- Preserve the existing indexed GitHub Pages URL: https://fadhel-docom.github.io/auto-blog/
- Do not change config.toml baseURL or switch canonical URLs to the temporary Cloudflare Pages hostname during stabilization.
- Do not purchase or require a custom domain.

## Findings verified in repository
1. config.toml currently sets baseURL to the GitHub Pages project URL.
2. layouts/_default/baseof.html emits canonical tags from Hugo .Permalink, so canonical URLs depend directly on the configured baseURL.
3. static/robots.txt allows crawling and points to the GitHub Pages sitemap.
4. .github/workflows/site_deploy.yml built Hugo and checked homepage, sitemap and RSS, but previously did not fail the build if canonical/sitemap/robots URLs drifted to a temporary hostname.
5. The Cloudflare deployment log supplied for deployment 87326bd1-d9b7-4a9a-b9e3-c0a01da8e02e explicitly said 'No build command specified. Skipping build step.' This proves that deployment did not run Hugo; it is not evidence that the Cloudflare build fix is now deployed.
6. Repository automation health snapshot dated 2026-10-27 reported homepage, sitemap and RSS as HTTP 200 on the stable GitHub Pages URL. It also reported GoatCounter traffic endpoint HTTP 404, which is an analytics issue and not proof of a Google indexing cause.
7. Repository state alone cannot reveal Google's exact exclusion reason. Search Console Page Indexing and URL Inspection are required to distinguish crawled-not-indexed, duplicate/canonical, blocked, soft-404, and availability problems.

## Action taken by ChatGPT
- Commit 86ae0a2a48a8ba8ab3654a0d4140de6dab05c5cf: added a pre-deployment CI guard in .github/workflows/site_deploy.yml requiring public/index.html, public/sitemap.xml, public/index.xml, and public/robots.txt, checking that homepage/sitemap/robots point to the stable GitHub Pages URL and that the temporary Cloudflare hostname is absent from key production SEO outputs.

## Next required checks (do not claim complete until evidenced)
1. Inspect the workflow run triggered by the CI-guard commit; confirm build and all checks pass.
2. Inspect live GitHub Pages homepage HTML, representative post HTML, sitemap and robots.txt from a real HTTP client; verify status 200, canonical host/path, no noindex, and expected URLs.
3. Compare every sitemap URL with the live response; fix any 404s and internal-link/base-path failures.
4. In Google Search Console for the exact GitHub Pages URL-prefix property, inspect one indexed URL and two excluded URLs. Record the exact Page indexing reason and URL Inspection canonical (user-declared and Google-selected).
5. Do not mass-submit URLs or change canonical host until these checks identify the cause. After a confirmed technical repair, request indexing for the homepage and a small set of representative high-value posts and monitor the report.

## Message for Claude
Continue from this incident log. The CI guard was added, but this does not itself prove the indexing issue is fixed. Preserve the stable GitHub Pages baseURL and coordinate on evidence from the next workflow run, live HTTP checks, and Search Console exclusion reasons. Do not reintroduce a custom-domain migration or promote the temporary pages.dev hostname as the canonical URL.
