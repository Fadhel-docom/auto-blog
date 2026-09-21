#!/usr/bin/env python3

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"

IMAGE_COUNT = 10


def configure_python_path() -> None:
    scripts_path = str(SCRIPTS_DIR)

    if scripts_path not in sys.path:
        sys.path.insert(
            0,
            scripts_path,
        )


def load_fetch_image_module():
    configure_python_path()

    try:
        import fetch_image

    except ImportError as exc:
        raise RuntimeError(
            "Could not import scripts/fetch_image.py. "
            f"Expected module at: "
            f"{SCRIPTS_DIR / 'fetch_image.py'}"
        ) from exc

    return fetch_image


def main() -> int:
    print("=" * 70)
    print("COMPETITIVE PEXELS FETCH")
    print("=" * 70)

    print(f"Repository root: {ROOT_DIR}")
    print(f"Scripts directory: {SCRIPTS_DIR}")
    print(f"Requested image count: {IMAGE_COUNT}")

    try:
        fetch_image = load_fetch_image_module()

        original_count = getattr(
            fetch_image,
            "IMAGE_COUNT",
            None,
        )

        print(
            "Original fetch_image.IMAGE_COUNT: "
            f"{original_count}"
        )

        fetch_image.IMAGE_COUNT = IMAGE_COUNT

        print(
            "Temporary fetch_image.IMAGE_COUNT: "
            f"{fetch_image.IMAGE_COUNT}"
        )

        result = fetch_image.main()

        if result is None:
            result = 0

        if not isinstance(result, int):
            result = 0

        if result != 0:
            print("", file=sys.stderr)
            print(
                "Pexels downloader returned "
                f"exit code {result}.",
                file=sys.stderr,
            )
            return result

        print("")
        print("Pexels downloader completed.")
        print(f"Expected image count: {IMAGE_COUNT}")

        print("=" * 70)
        print("COMPETITIVE PEXELS FETCH COMPLETE")
        print("=" * 70)

        return 0

    except KeyboardInterrupt:
        print("", file=sys.stderr)
        print("Operation cancelled.", file=sys.stderr)
        return 130

    except Exception as exc:
        print("", file=sys.stderr)
        print("COMPETITIVE PEXELS FETCH FAILED", file=sys.stderr)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
