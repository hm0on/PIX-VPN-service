"""structlog → JSON-to-stdout setup for the worker.

Single source of truth for log configuration. Called once on startup;
ARQ's own logger is rerouted through stdlib so its records also end up
as JSON lines.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import orjson
import structlog
from structlog.types import EventDict, Processor


def _orjson_dumps(obj: Any, default: Any = None) -> str:
    """Serialize log dict via orjson (faster) and decode to str."""
    return orjson.dumps(obj, default=default).decode("utf-8")


def _add_service(_: Any, __: str, event_dict: EventDict) -> EventDict:
    """Tag every record with the service name for log aggregation."""
    event_dict.setdefault("service", "worker")
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog + stdlib logging to emit JSON lines on stdout."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    # ----- stdlib root logger: minimal handler, structlog will format -----
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Make ARQ's own logs look the same — structlog will pick them up via
    # ProcessorFormatter; for now we keep stdlib handler simple and route
    # its records through structlog by setting a JSON formatter.
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(serializer=_orjson_dumps),
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            _add_service,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
        ],
    )
    handler.setFormatter(formatter)

    # ----- structlog itself -----
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _add_service,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )

    # Quiet down noisy third-party libs
    for noisy in ("asyncio", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(max(log_level, logging.WARNING))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a configured structlog logger."""
    return structlog.stdlib.get_logger(name) if name else structlog.stdlib.get_logger()
