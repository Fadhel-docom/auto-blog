# Automation Control Plane

## Mission
Keep Home Organization Ideas stable, safe, observable, and maintainable before optimizing publishing volume.

## Operating mode
**EMERGENCY ROLLBACK — PUBLISHING PAUSED**

Scheduled publishing is paused after the custom-domain migration was found to be broken. The project has been rolled back to the known Google-indexed GitHub Pages URL while the custom domain remains off. No new generator call is allowed during this recovery.

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
1. Publishing remains disabled until the stabilization gates below pass.
2. No automatic retry on provider rate limits.
3. A 429 is an availability condition, not a reason to spend more generation calls.
4. Cancelled/timed-out publisher runs must enter the repair path.
5. A pending/blocked workflow is a health incident, not a successful publish.
6. Queue items are finalized only after live-site verification.
7. Health monitoring must not call content generators.
8. OpenAI Quality Gate must remain independent from the generator that produced the draft.
9. Every recovery must be followed by real workflow verification before being declared fixed.
10. No URL/domain migration while stabilization is active.

## Project execution phases
**Phase 1 — Site organization:** structure, navigation, technical SEO, legal pages, canonical/baseURL consistency, deployment health.
**Phase 2 — Error repair:** 404s, broken links, malformed metadata, build/deploy errors, sitemap/robots/RSS and mobile/UI checks.
**Phase 3 — Article repair:** review every published article for originality, usefulness, structure, factual clarity, internal links, metadata and duplicate topics.
**Phase 4 — Image repair:** audit every article image, detect byte-identical duplicates, repair references before removing any asset, and require meaningful image variation.
**Phase 5 — Value & legality gate:** useful problem-solving content, transparent authorship/editorial policy, privacy/contact/legal pages, image/source rights and no deceptive traffic tactics.
**Phase 6 — Team activation:** Generator → Image/SEO → OpenAI Quality Gate → Hugo/deploy → live verification → queue finalization. Auto Repair handles deterministic failures; Health Monitor stays lightweight.
**Phase 7 — Controlled publishing:** after all gates pass, publish exactly 2 high-quality articles/day at the established schedule; never publish merely to fill a quota.
**Phase 8 — Indexation & compliant traffic:** Search Console/Bing/indexation monitoring first, then legitimate discovery channels and analytics; no spam, artificial traffic or deceptive links.

## Readiness gate
Publishing can be re-enabled only after all are true:
- Site deployment is live and verified on the stable GitHub Pages URL.
- Homepage, sitemap, RSS, robots.txt, representative posts and images pass live checks.
- No unresolved critical 404/internal-link issue remains.
- Article and image audits have been completed and duplicate assets have been safely resolved.
- Legal/editorial pages are present and internally linked.
- Scheduled Publisher passes one controlled end-to-end test.
- Generate -> images -> SEO -> Quality Gate -> Hugo -> deploy -> live verification -> queue finalize passes in one run.
- Auto Repair handles failure/cancellation/timeout without retry storms.
- Health Monitor remains green for several cycles.
- No unresolved critical automation issue remains.
- Content quality checks pass on the latest article.

## Team operating model
- **Manager / Orchestrator:** ChatGPT — sequencing, evidence, approvals, rollback decisions.
- **Technical/SEO guardian:** deterministic checks — URLs, canonical, sitemap, robots, redirects and indexability.
- **Content generators:** OpenAI / Groq / OpenRouter — drafting only; bounded and cooperative.
- **Image worker:** image acquisition/validation and duplicate detection; never reuse identical assets across unrelated articles.
- **Editorial Quality Gate:** OpenAI — independent fail-closed review.
- **Repair Agent:** Auto Repair — deterministic state repair only.
- **Health Monitor:** every 15 minutes, lightweight checks only; never calls generators.
- **Traffic monitor:** GoatCounter — measurement, not artificial traffic generation.

## Review rhythm
- Health Monitor: every 15 minutes, lightweight.
- Manager review: after material incidents and at least once/twice weekly.
- Publishing: 2 articles/day only after the stability gate is green.
- Indexation/traffic work: only after the publishing pipeline is proven stable.

## Current state / blockers
## Current state / blockers
1. Verify the rollback deployment on `https://fadhel-docom.github.io/auto-blog/` (homepage, sitemap, RSS, HTTPS, and a real post).
2. Verify that published URLs and generated canonicals are back on the indexed GitHub Pages property.
3. Keep the custom domain migration frozen; do not touch Search Console Change of Address yet.
4. Only after the old site is healthy, prepare a separate controlled custom-domain migration.
3. Run one controlled end-to-end publisher test manually; do not restore the 10-minute schedule until it passes.
4. Verify Auto Repair, OpenAI Quality Gate, and Health Monitor behavior without retry storms or generator waste.
5. Only then resume article/design optimization and normal publishing.

## Next phase
1. Finish stable GitHub Pages deployment verification.
2. Complete site/error/article/image audits.
3. Apply safe repairs and verify deployment after each grouped change.
4. Activate the team only after the stability gate is green.
5. Restore exactly two quality publishing slots/day.
6. Begin indexation monitoring and compliant traffic acquisition.
