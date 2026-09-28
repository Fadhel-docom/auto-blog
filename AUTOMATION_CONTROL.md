# Automation Control Plane

## Mission
Keep Home Organization Ideas stable, safe, observable, and maintainable before optimizing publishing volume.

## Operating mode
**STABILIZATION — PUBLISHING PAUSED**

Scheduled publishing is paused while the canonical-domain migration is repaired and verified. No new generator call is allowed until the live production domain, redirects/canonicals, and end-to-end publishing path are proven healthy.

## Team roles
- **Manager / Orchestrator:** ChatGPT — owns sequencing, evidence, rollback decisions, and the single source of truth for the project.
- **Migration / SEO guardian:** deterministic checks — protects canonical URLs, sitemap, robots.txt, queue URLs, and legacy-link continuity; no destructive URL changes during stabilization.
- **Generator team:** OpenAI / Groq / OpenRouter — content generation only, used cooperatively and never hammered when providers are rate-limited.
- **Editorial Quality Gate:** OpenAI — independent quality decision; failure is fail-closed.
- **Repair Agent:** Auto Repair — diagnoses completed failures and repairs deterministic state problems.
- **Health Monitor:** every 15 minutes; lightweight checks first, no generation calls.
- **SEO / Site checks:** deterministic scripts; no LLM call unless explicitly required.
- **Traffic monitor:** GoatCounter reporting; observation only.

## Rules
1. No automatic publishing while this file says STABILIZATION.
2. No automatic retry on provider rate limits.
3. A 429 is an availability condition, not a reason to spend more generation calls.
4. Cancelled/timed-out publisher runs must enter the repair path.
5. A pending/blocked workflow is a health incident, not a successful publish.
6. Queue items are finalized only after live-site verification.
7. Health monitoring must not call content generators.
8. OpenAI Quality Gate must remain independent from the generator that produced the draft.
9. Every recovery must be followed by a real workflow verification before being declared fixed.

## Readiness gate
Publishing can be re-enabled only after all are true:
- Scheduled Publisher has a clean end-to-end test.
- Generate -> images -> SEO -> Quality Gate -> Hugo -> deploy -> live verification -> queue finalize all pass in one run.
- Auto Repair handles failure, cancellation, and timeout without creating retry storms.
- Provider rate-limit behavior is bounded and produces no retry loop.
- Health Monitor remains green for at least several cycles.
- No unresolved critical automation issue remains.
- The live site uses the production custom domain and canonical URLs.
- Content quality checks pass on the latest article.

## Review rhythm
- Health Monitor: every 15 minutes, lightweight.
- Manager review: after material incidents and at least once/twice weekly.
- Publishing optimization: only after the stability gate is green.

## Current state / blockers
- Canonical domain migration is incomplete at the DNS layer: repository configuration is set to `home-organization-ideas.com`, but live DNS resolution is currently failing. GitHub Pages custom-domain DNS must be repaired before publishing resumes.
- Legacy published queue URLs have been migrated in `keywords.csv` to the canonical domain, and Auto Repair now uses the canonical post URL base. The previous GitHub Pages URL remains preserved in Git history and the stabilization backup branch.
- Provider rate limits previously caused repeated generation failures; retries remain bounded and the publisher must never enter a retry storm.
- One legacy Scheduled Publisher run remains pending from before the stabilization pause; it is not being treated as proof of successful publishing.
- One queue item remains overdue by design while publishing is paused.
- The latest article quality issue was repaired: it now has 6 unique inline images, 10 H2 sections, 5 FAQs, and 2,169 words.
- Link Audit is green after repairing two broken internal links.
- Auto Repair handles failure/cancellation/timeout events and preserves cooldown state.

## Next phase
1. Repair DNS for `home-organization-ideas.com` and verify homepage, sitemap, RSS, HTTPS, and a real post.
2. Verify canonical/legacy URL continuity and external platform links before changing any more URLs.
3. Run one controlled end-to-end publisher test manually; do not restore the 10-minute schedule until it passes.
4. Verify Auto Repair, OpenAI Quality Gate, and Health Monitor behavior without retry storms or generator waste.
5. Only then resume article/design optimization and normal publishing.
