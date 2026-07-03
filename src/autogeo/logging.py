"""Structured logging: console or JSON-lines, with per-document context.

Every record carries `doc_id` and `stage` from contextvars so batch logs are
filterable per document without threading loggers through every call.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

doc_id_var: ContextVar[str | None] = ContextVar("autogeo_doc_id", default=None)
stage_var: ContextVar[str | None] = ContextVar("autogeo_stage", default=None)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.doc_id = doc_id_var.get() or "-"
        record.stage = stage_var.get() or "-"
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "doc_id": getattr(record, "doc_id", "-"),
            "stage": getattr(record, "stage", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_CONSOLE_FMT = "%(asctime)s %(levelname)-7s [%(doc_id)s/%(stage)s] %(name)s: %(message)s"


def setup_logging(level: str = "INFO", fmt: str = "console") -> None:
    """Configure the root autogeo logger. Idempotent."""
    root = logging.getLogger("autogeo")
    root.setLevel(level.upper())
    if any(getattr(h, "_autogeo", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter() if fmt == "json" else logging.Formatter(_CONSOLE_FMT))
    handler.addFilter(_ContextFilter())
    handler._autogeo = True  # type: ignore[attr-defined]
    root.addHandler(handler)


def add_workdir_log(workdir: Path) -> logging.Handler:
    """Attach a per-document JSON-lines log file (`log.jsonl`) under `workdir`."""
    workdir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(workdir / "log.jsonl", encoding="utf-8")
    handler.setFormatter(_JsonFormatter())
    handler.addFilter(_ContextFilter())
    logging.getLogger("autogeo").addHandler(handler)
    return handler


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"autogeo.{name}")
