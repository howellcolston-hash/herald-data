"""Guards the workflows run before every commit.

    python -m herald.check

Fails (exit 1) when any file in the repository is over the 95 MB cap. Prints the size of data/ and views/ and
warns when data/ passes 600 MB, well before the 1 GB the repository must stay under.
"""

from __future__ import annotations

import sys

from collectors import common

WARN_DATA_BYTES = 600 * 1024 * 1024


def main() -> int:
    root = common.REPO_ROOT
    too_big, totals = [], {}
    for p in root.rglob("*"):
        if ".git" in p.parts or ".cache" in p.parts or not p.is_file():
            continue
        size = p.stat().st_size
        top = p.relative_to(root).parts[0]
        totals[top] = totals.get(top, 0) + size
        if size > common.MAX_FILE_BYTES:
            too_big.append((p.relative_to(root), size))
    for name in ("data", "views"):
        print(f"{name}/: {totals.get(name, 0) / 1e6:.1f} MB")
    if totals.get("data", 0) > WARN_DATA_BYTES:
        print(f"warning: data/ is over {WARN_DATA_BYTES / 1e6:.0f} MB", file=sys.stderr)
    for p, size in too_big:
        print(f"error: {p} is {size / 1e6:.1f} MB, over the {common.MAX_FILE_BYTES / 1e6:.0f} MB cap", file=sys.stderr)
    return 1 if too_big else 0


if __name__ == "__main__":
    raise SystemExit(main())
