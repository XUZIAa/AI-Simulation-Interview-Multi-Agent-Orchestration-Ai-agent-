from __future__ import annotations

import sys

from .ui.app import run


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
