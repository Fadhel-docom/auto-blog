# cover_fetch_plan.md

## 1. تشغيل يدوي دون تشغيل النشر

- Workflow: `Scheduled Publisher` — `.github/workflows/daily.yml`
- Inputs بعد التعديل: `mode=covers` و`cover_slugs` (قائمة slugs مفصولة بفواصل).
- الوضع الحالي: `workflow_dispatch` لا يعرّف inputs؛ ولا يتيح اختيار مقال. تشغيله الآن يشغّل مسار النشر.
- الأمر بعد تطبيق patch الـworkflow أدناه:

```bash
gh workflow run daily.yml --ref main -f mode=covers -f cover_slugs='small-laundry-room-organization-ideas-smart-storage,small-bedroom-organization-ideas-practical-space,renter-friendly-storage-ideas-small-kitchen-four'
```

لمقال واحد، مرّر slug واحدًا فقط في `cover_slugs`. تشغيل `mode=covers` يشغّل وظيفة الأغلفة فقط؛ وظيفة النشر لا تعمل.

## 2. Patch: `scripts/competitive_fetch.py`

```diff
diff --git a/scripts/competitive_fetch.py b/scripts/competitive_fetch.py
--- a/scripts/competitive_fetch.py
+++ b/scripts/competitive_fetch.py
@@
 MAX_IMAGE_SEARCH_SECONDS = 300
+
+COVER_QUERIES = {
+    "small-laundry-room-organization-ideas-smart-storage":
+        "small laundry room organization storage shelves baskets",
+    "small-bedroom-organization-ideas-practical-space":
+        "small bedroom organization practical storage",
+    "renter-friendly-storage-ideas-small-kitchen-four":
+        "small renter friendly kitchen storage cabinets shelves",
+}
@@
 # ============================================================================
 # Entry point
 # ============================================================================
+
+def fetch_cover_only(api_key: str, slug: str) -> int:
+    query = COVER_QUERIES.get(slug)
+    if not query:
+        raise ValueError(f"Unsupported cover slug: {slug}")
+
+    tracker = load_global_tracker()
+    cleanup_old_ids(tracker)
+    candidates = collect_candidates(
+        api_key,
+        query,
+        search_query=query,
+        deadline=time.monotonic() + MAX_IMAGE_SEARCH_SECONDS,
+    )
+    best = choose_best_candidate(
+        candidates,
+        set(tracker.get("used_ids", [])),
+        set(tracker.get("used_photographers", [])),
+    )
+    if best is None:
+        raise RuntimeError(f"No suitable Pexels cover found for {slug}")
+
+    destination = IMAGE_DIR / f"{slug}-cover.jpg"
+    download_image(best["image_url"], destination)
+    add_used_ids(
+        tracker,
+        [best["id"]],
+        [best["photographer"]] if best.get("photographer") else [],
+    )
+    cleanup_old_ids(tracker)
+    save_global_tracker(tracker)
+    print(f"COVER_FILE={destination.relative_to(ROOT_DIR)}")
+    print(f"PEXELS_PHOTO_ID={best['id']}")
+    print(f"PHOTOGRAPHER={best.get('photographer', '')}")
+    print(f"PHOTOGRAPHER_URL={best.get('photographer_url', '')}")
+    print(f"PEXELS_URL={best.get('pexels_url', '')}")
+    print(f"IMAGE_WIDTH={best.get('width', 0)}")
+    return 0
+
 
 def main() -> int:
+    if len(sys.argv) == 3 and sys.argv[1] == "--cover-slug":
+        try:
+            return fetch_cover_only(
+                get_required_env("PEXELS_API_KEY"),
+                sys.argv[2],
+            )
+        except Exception as exc:
+            print(f"COVER FETCH FAILED: {exc}", file=sys.stderr)
+            return 1
+
     print("=" * 70)
*** End Patch
```

## 3. Patch: `.github/workflows/daily.yml`

```diff
diff --git a/.github/workflows/daily.yml b/.github/workflows/daily.yml
--- a/.github/workflows/daily.yml
+++ b/.github/workflows/daily.yml
@@
-  workflow_dispatch:
+  workflow_dispatch:
+    inputs:
+      mode:
+        description: "publish runs the existing publisher; covers fetches only selected cover images"
+        type: choice
+        options:
+          - publish
+          - covers
+        default: publish
+        required: true
+      cover_slugs:
+        description: "Comma-separated supported slugs; used only when mode=covers"
+        type: string
+        required: false
@@
 jobs:
   publish:
+    if: inputs.mode != 'covers'
     runs-on: ubuntu-latest
@@
       - name: Recovery check
         run: |
           python scripts/queue_manager.py status
           echo "Recovery check passed: no active due articles remain. Cooldown items will be retried after their rest period."
+
+  cover-fetch:
+    if: inputs.mode == 'covers'
+    runs-on: ubuntu-latest
+    timeout-minutes: 15
+    steps:
+      - name: Checkout
+        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683
+      - name: Setup Python
+        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97
+        with:
+          python-version: "3.11"
+      - name: Install dependencies
+        run: python -m pip install requests
+      - name: Fetch selected covers
+        env:
+          PEXELS_API_KEY: ${{ secrets.PEXELS_API_KEY }}
+        shell: bash
+        run: |
+          set -euo pipefail
+          test -n "${{ inputs.cover_slugs }}"
+          IFS=',' read -ra SLUGS <<< "${{ inputs.cover_slugs }}"
+          for raw_slug in "${SLUGS[@]}"; do
+            slug="$(printf '%s' "$raw_slug" | xargs)"
+            test -n "$slug"
+            python scripts/competitive_fetch.py --cover-slug "$slug"
+          done
+      - name: Commit cover images
+        run: |
+          git config user.name "github-actions[bot]"
+          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
+          git add static/images/
+          git diff --cached --quiet && { echo "No cover images changed"; exit 1; }
+          git commit -m "Fetch selected Pexels cover images"
+          git push
*** End Patch
```

## 4. المقالات الثلاثة

- `small-laundry-room-organization-ideas-smart-storage`
  - Pexels query: `small laundry room organization storage shelves baskets`
  - الملف الناتج: `static/images/small-laundry-room-organization-ideas-smart-storage-cover.jpg`

- `small-bedroom-organization-ideas-practical-space`
  - Pexels query: `small bedroom organization practical storage`
  - الملف الناتج: `static/images/small-bedroom-organization-ideas-practical-space-cover.jpg`

- `renter-friendly-storage-ideas-small-kitchen-four`
  - Pexels query: `small renter friendly kitchen storage cabinets shelves`
  - الملف الناتج: `static/images/renter-friendly-storage-ideas-small-kitchen-four-cover.jpg`

## 5. خطوات Claude بعد ذلك بالترتيب

1. تعديل `scripts/competitive_fetch.py` بتطبيق patch أعلاه.
2. تعديل `.github/workflows/daily.yml` بتطبيق patch أعلاه، مع التأكد أن `publish` يعمل فقط عندما `mode != covers`.
3. تشغيل الأمر أعلاه؛ انتظر نجاح job `cover-fetch` وتحقق من وجود ملفات JPG الثلاثة في `static/images/`.
4. لكل مقال، تعديل front matter الحالي `image = "images/…"` ليشير إلى اسم الغلاف الجديد مع الحفاظ على صيغة الحقل التي يستخدمها الموقع؛ لا تضف `cover` بدل `image` دون تعديل القالب.
5. إضافة اعتماد الصورة أسفل المقال بصيغة تتضمن رابط صورة Pexels، اسم المصور، ورابط ترخيص Pexels.
6. دليل النجاح لكل slug: ملف JPG موجود وصالح وأبعاده `width >= 1600`؛ front matter يشير إلى `images/<slug>-cover.jpg`؛ credits تتضمن رابط Pexels واسم المصور والترخيص؛ ثم تشغيل Quality Gate وبناء Hugo للتحقق.
