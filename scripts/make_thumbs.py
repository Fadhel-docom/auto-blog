#!/usr/bin/env python3
"""Build-time responsive thumbnails for raster images in static/images.

Writes static/images/thumbs/<stem>-<width>.jpg (640/960/1280 px wide) only when the
source is wider than the target. Originals are never modified. Generated files are
not committed; the Site Deploy workflow creates them right before the Hugo build.
"""
from pathlib import Path
from PIL import Image, ImageOps

SRC = Path("static/images")
OUT = SRC / "thumbs"
WIDTHS = (640, 960, 1280)
QUALITY = 80


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    made = skipped = failed = 0
    for p in sorted(SRC.iterdir()):
        if not p.is_file() or p.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        try:
            with Image.open(p) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                w, h = im.size
                for tw in WIDTHS:
                    if w <= tw:
                        skipped += 1
                        continue
                    th = max(1, round(h * tw / w))
                    im.resize((tw, th), Image.LANCZOS).save(
                        OUT / f"{p.stem}-{tw}.jpg",
                        "JPEG",
                        quality=QUALITY,
                        optimize=True,
                        progressive=True,
                    )
                    made += 1
        except Exception as exc:  # never break the deploy because of one image
            failed += 1
            print(f"thumb skipped for {p.name}: {exc}")
    print(f"thumbnails: made={made} skipped_small={skipped} failed={failed}")


if __name__ == "__main__":
    main()
