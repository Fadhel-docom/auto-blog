# HomeOrg SEO, Discovery & Revenue Plan
**Prepared:** 2026-10-26  
**Owner:** ChatGPT — research, SEO strategy, internal-linking audit  
**Scope:** Evidence-led recommendations only; no content files, protected templates, publishing, or workflow runs changed.

## Executive priorities

1. **Fix crawlable discovery paths on the homepage.** The current `layouts/index.html` source has five category filters implemented as buttons, not crawlable links; the visible “Browse by room” anchor points to `#browse-rooms`, but the current source excerpt contains no matching target. The category buttons are also followed by a closing `</div>` without a visible opening `<div class="category-filters">`. This is consistent with the existing DOM diagnosis in Operations Room #109. These are high-priority UX/discovery issues, but the template is protected: implement only in a separate, explicitly scoped PR after the owner confirms the exception.
2. **Do not treat sitemap submission as the fix.** The latest Search Console notes in #109 say the category page was indexed, while sampled posts were “URL is unknown to Google”; sitemap entries were pending with zero reported errors. That points to discovery/coverage investigation, not proof of a broken sitemap. Obtain the Search Console Page indexing report before changing sitemap settings or requesting mass indexing.
3. **Build topic clusters around practical, specific problems.** Compete on useful long-tail answers for small homes and constrained storage, rather than broad head terms dominated by major publishers.
4. **Improve the path to revenue only after trust and usefulness.** Add genuinely useful product recommendations where they solve a stated storage problem, clearly disclose affiliate relationships, and avoid thin “best products” pages. Do not buy a domain or spend money as a prerequisite.

## Competitor observations (qualitative; no search-volume claims)

Research reviewed on 2026-10-26:
- **Good Housekeeping:** recent organizing coverage uses expert-backed checklists, specific room/problem angles, and actionable lists. Its Oct. 8, 2026 report highlighted increased demand for apartment, bathroom, and kitchen organization.  
  Source: https://www.goodhousekeeping.com/home/organizing/a74065940/home-organization-trend-taskrabbit/
- **Apartment Therapy:** its small-space storage guide emphasizes vertical storage, behind-door space, multifunctional furniture, and product examples.  
  Source: https://www.apartmenttherapy.com/small-space-storage-ideas-268691
- **The Spruce:** its small laundry-room guide offers multiple concrete solutions, including shelves, appliance-adjacent space, dividers, and hanging rods.  
  Source: https://www.thespruce.com/small-laundry-room-organization-ideas-5509293
- **The Small Nest:** its small-space guide is organized as a repeatable system: declutter first, zone each room, use vertical/hidden storage, contain categories, then maintain habits.  
  Source: https://thesmallnest.com/start-here.html

**What HomeOrg should learn—not copy:** combine a clear step-by-step method with measurements/constraints, budget alternatives, renter-safe options, before/after decision criteria, and links to closely related guides. Major sites often win breadth and authority; HomeOrg can differentiate through narrower, genuinely useful solutions for one specific space/problem per article.

## Keyword opportunity map

These are **intent-based candidates**, not measured search-volume or ranking claims. Validate them against Search Console queries and a keyword tool before assigning exact targets.

| Priority | Search intent / candidate cluster | Content angle | Internal links to connect |
|---|---|---|---|
| P1 | small closet organization ideas; small closet storage for apartments | Use vertical space, door clearance, shelf depth, seasonal rotation, no-renovation options | bedroom/closet guides; small-space guides |
| P1 | small laundry room organization ideas; laundry room storage for tight spaces | Between/above-appliance storage, folding surface, sorting, renter-safe solutions | bathroom-and-laundry guides; small-space guides |
| P1 | under-sink organization ideas; bathroom storage for small bathrooms | Measure pipe clearance, leak-safe containers, daily-use zones | bathroom-and-laundry guides; decluttering guides |
| P1 | kitchen cabinet organization for small kitchens; narrow cabinet storage | Group by task, vertical dividers, door interiors, keep frequently used items accessible | kitchen guides; small-space guides |
| P2 | entryway organization for small spaces; no-mudroom drop zone | Shoes, bags, mail, hooks, a small defined landing zone | living-room-and-entry guides; closet guides |
| P2 | small bedroom storage ideas; under-bed storage organization | Bed clearance, seasonal items, avoid blocking airflow/access | bedroom/closet guides; small-space guides |
| P2 | decluttering checklist by room; how to declutter a small home | Small sessions, keep/donate/relocate decisions, maintenance reset | all five room categories |
| P2 | renter-friendly storage ideas; no-drill organization | Reversible solutions, surface-safe options, measuring before purchase | relevant room guides |

**Editorial rule:** one primary intent per page. Do not create multiple pages that only swap a room word into the same outline. Each page should solve a distinct problem and answer practical constraints competitors leave vague.

## Internal-linking actions

### A. Crawlable category navigation
- Keep the five official category names and paths unchanged.
- Add ordinary HTML anchors to all five category pages; JavaScript filters may remain as an enhancement but should not be the only discovery path.
- Add the missing `browse-rooms` target so the hero anchor reaches a real section.
- Repair the missing `category-filters` wrapper in the homepage markup. Because `layouts/index.html` is protected, do this only in a separate PR after explicit scope approval. Do not combine with CSS PRs #111–#113.

### B. Contextual links inside articles
For each existing article, add links only where they genuinely help the reader:
- **One parent/category link** near the introduction or in a small “Explore this room” module.
- **Two to four relevant sibling guides** near the section where the related problem is discussed, not as a generic link dump.
- **One next-step guide** at the end (for example, from a closet article to a decluttering checklist).
- Use descriptive anchors that tell readers what they will get; avoid repeated exact-match keyword anchors on every page.
- Check for orphan pages and pages receiving no meaningful internal links. Prioritize the most useful, unique guides rather than creating links to every tag archive.

### C. Taxonomy and sitemap
- Keep the five strategic room categories prominent.
- Audit the large tag archive set before giving it priority; thin/near-duplicate tag pages should not outrank useful guides in navigation.
- Do not delete sitemap entries, change canonical/baseURL, or submit mass indexing requests based on “pending” alone. Use the Page indexing report and live URL inspection evidence first.

## On-page checklist for existing and future guides

- Title states the room/problem and concrete benefit; avoid generic “ultimate/best” claims without evidence.
- Meta description explains who the solution helps and what practical outcome the reader gets.
- Opening paragraph answers the query quickly; include the key constraints (small room, rental, budget, measurements) when relevant.
- Use descriptive H2s organized around decisions or steps, not keyword repetition.
- Include original details competitors cannot supply by repeating generic tips: measurements to check, common mistakes, what not to buy, low-cost alternatives, and when a solution will not work.
- Images have meaningful alt text describing the useful content of the image, not keyword lists.
- Add FAQ content only when it answers real follow-up questions; do not add schema as a substitute for useful answers.
- Verify canonical URL, indexability, internal links, image loading, and mobile readability before calling a page complete.

## Revenue path without buying a domain

1. **First:** improve discovery and publish/refresh genuinely useful pages under the existing GitHub Pages URL. A domain purchase is not a prerequisite for this work.
2. **Then:** test relevant affiliate links only where a product genuinely solves a stated problem (for example, a narrow over-door organizer after explaining door clearance). Clearly disclose affiliate relationships near recommendations and follow each program's terms.
3. **Use Pinterest as a distribution channel:** create original vertical pins for the site's most useful guides, link each pin directly to the relevant guide, and track outbound clicks where available. Do not mass-produce near-identical pins.
4. **Measure outcomes:** Search Console impressions/clicks/indexing; outbound affiliate clicks and conversions if the program provides reports; top landing pages; and which topics lead to meaningful engagement. Do not infer revenue potential from rankings or traffic alone.
5. **Avoid early distractions:** no paid tools, paid backlinks, bulk AI pages, or domain purchase before evidence supports the spend. Ad-network acceptance and earnings are not guaranteed.

## 30-day execution sequence

- **Days 1–3:** capture the Page indexing report and query/page exports; confirm which important URLs Google knows; record current indexed pages and impressions.
- **Days 1–5 (parallel):** obtain owner approval for a narrowly scoped homepage-template PR covering crawlable category links, the missing anchor target, the category wrapper, and duplicate hero/featured image handling. Keep it separate from #111–#113.
- **Week 1:** map all current article URLs to one primary intent and five-category cluster; identify orphans, duplicate intents, and strongest pages using actual Search Console data.
- **Week 2:** implement internal links in a separate approved change set; no changes to `content/posts/` until the owner explicitly authorizes a specific batch.
- **Weeks 2–4:** prioritize a small batch of pages based on existing impressions and clear intent gaps; refresh titles/descriptions/sections only after query evidence is reviewed.
- **Weekly:** log changes and outcomes in Operations Room #109. Do not repeatedly resubmit the same sitemap or request mass indexing without new evidence.

## Evidence and limitations

- Repository source reviewed: `config.toml`, `layouts/_default/baseof.html`, `layouts/_default/single.html`, `layouts/index.html`, and `static/robots.txt`.
- The configured canonical base is `https://fadhel-docom.github.io/auto-blog/`; robots.txt points to `https://fadhel-docom.github.io/auto-blog/sitemap.xml`.
- Existing Operations Room notes dated 2026-10-25 report that `/categories/` was indexed while two sampled article URLs were “URL is unknown to Google”; this is evidence for those sampled URLs at that time, not a full current coverage report.
- No search-volume metrics, competitor traffic estimates, live browser visual tests, builds, sitemap submissions, indexing requests, deployments, or content changes were performed as part of this research.
