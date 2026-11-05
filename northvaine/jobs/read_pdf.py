"""Read a PDF catalogue in its own process (D144): the text, page count and readability.

    python -m northvaine.jobs.read_pdf <in.pdf> <out.json>

Exit 0 with the result written; 1 when the file is not a readable PDF.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python -m northvaine.jobs.read_pdf <in.pdf> <out.json>", file=sys.stderr)
        return 2
    from northvaine.radar.onboarding import read_catalogue

    try:
        read = read_catalogue(Path(sys.argv[1]).read_bytes())
    except Exception:
        return 1
    Path(sys.argv[2]).write_text(read.model_dump_json(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
