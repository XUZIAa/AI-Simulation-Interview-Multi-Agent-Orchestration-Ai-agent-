from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .paths import log_dir

_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(level)

    file_handler = RotatingFileHandler(
        log_dir() / "app.log", maxBytes=4 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)

    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(stream)

    for noisy in ("websockets.client", "httpx", "httpcore", "pdfminer", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
