# Article Quality Audit — 2026-10-21

Scope: all 28 Markdown files currently present in `content/posts/` on `main`. This is a source-repository audit; it does not claim that every file is published or indexed.

## Summary

- Articles audited: **28**.
- Word-count range (body only): **1,223–3,293 words**.
- Internal `/posts/.../` links checked against article slugs: **no missing targets found**.
- Local image references: the three `../images/...svg` references in the renter-friendly bathroom article point to existing files under `static/images/`; the site's `render-image.html` hook normalizes image paths to their basename under `/images/`, so these are not treated as broken links.
- Source sections missing from article bodies: **2**, both currently marked `draft = true`; source sections were added to both files in this audit branch.
- Articles with ADA / Americans with Disabilities Act references: **13**. These repeatedly frame ordinary private-home layout suggestions using commercial accessibility standards. This should be an editorial cleanup pass: retain useful measurements only when described as optional planning targets, and remove ADA compliance framing/citations where they are not needed.
- Shorter bodies needing a human usefulness review (under 1,500 words): **5**. Length alone does not establish poor quality.

## Changes made in this branch

1. `bathroom-organization-maximizing-24-inch-deep-cabi.md`: added a factual `Sources` section for household-product storage and moisture/mold guidance. The article remains a draft.
2. `small-bathroom-organization-without-clutter.md`: added a factual `Sources` section and renamed the existing `Photo Sources` heading to `Photo Credits`. The article remains a draft.

## ADA-related editorial review queue

- `content/posts/30-practical-home-organization-ideas-for.md`
- `content/posts/bedroom-organization-stepbystep-48inch-clearance.md`
- `content/posts/decluttering-5x5-home-office-corner-remote-workers.md`
- `content/posts/effortless-home-organization-tips-for-small-spaces.md`
- `content/posts/holiday-decoration-storage-small-apartment-count-before-you-box.md`
- `content/posts/kitchen-storage-without-pantry-dry-goods-small-apartment.md`
- `content/posts/narrow-entryway-organization-drop-zone.md`
- `content/posts/renter-friendly-closet-organization-using-adhesive.md`
- `content/posts/renterfriendly-kitchen-organization-magnetic-spice.md`
- `content/posts/small-apartment-organization-maximizing-storage-in-a-350sqft.md`
- `content/posts/small-living-room-storage-ideas-renters.md`
- `content/posts/small-space-organization-transforming-a-3ft-wide-hallway-int.md`
- `content/posts/toy-storage-small-apartment-rotation-system.md`


No blind global replacement was applied to these articles because some passages include specific measurements, building-code claims, and FAQ answers. They should be rewritten contextually so the article remains useful and factual without implying that private homes must meet commercial accessibility standards.

## Shorter articles for manual usefulness review

- `30-practical-home-organization-ideas-for.md` — 1377 words
- `kitchen-organization-ideas-small-spaces-space.md` — 1333 words
- `small-apartment-storage-ideas-practical-space.md` — 1230 words
- `small-bedroom-storage-ideas-diy-pull-out.md` — 1226 words
- `small-closet-organization-ideas-practical-space.md` — 1223 words


## Verification limits

This audit checked repository structure, front matter, body length, source headings, article-to-article links, local image references, and known ADA wording. It did not perform live HTTP checks on every external URL, test every rendered page in a browser, or verify Google/Bing indexing. Those require separate checks.
