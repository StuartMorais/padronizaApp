from __future__ import annotations

import json
import logging
import sys
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

LOGGER_NAME = "padroniza"
_MAX_LOG_BYTES = 2 * 1024 * 1024
_BACKUP_COUNT = 5
_log_path: Path | None = None


@dataclass(frozen=True)
class ErrorReport:
    error_id: str
    stage: str
    timestamp: str
    message: str
    log_path: Path | None
    details: str


def configure_application_logging(storage_root: Path | str) -> Path:
    """Configure bounded application logs under persistent storage.

    Reconfiguration is supported so tests, portable storage changes, or future
    profile switching never leave the logger writing to an obsolete path.
    """

    global _log_path
    root = Path(storage_root).expanduser().resolve()
    log_dir = root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "padroniza.log"

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    matching_handler = None
    for handler in list(logger.handlers):
        if not isinstance(handler, RotatingFileHandler):
            continue
        try:
            handler_path = Path(handler.baseFilename).resolve()
        except (OSError, TypeError):
            handler_path = None
        if handler_path == path:
            matching_handler = handler
            continue
        logger.removeHandler(handler)
        handler.close()

    if matching_handler is None:
        matching_handler = RotatingFileHandler(
            path,
            maxBytes=_MAX_LOG_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        matching_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(matching_handler)

    _log_path = path
    logger.info("Application logging initialized")
    return path


def get_log_path() -> Path | None:
    return _log_path


def report_exception(
    stage: str,
    exc: BaseException,
    *,
    context: dict[str, Any] | None = None,
) -> ErrorReport:
    """Log an exception and return user-shareable technical details.

    Context should contain operational metadata only (template ID, path, backend,
    etc.). Form values and document contents should not be passed here.
    """

    error_id = uuid.uuid4().hex[:10].upper()
    timestamp = datetime.now().replace(microsecond=0).isoformat()
    safe_context = _safe_context(context or {})
    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    details_lines = [
        f"Erro: {error_id}",
        f"Etapa: {stage}",
        f"Horário: {timestamp}",
        f"Tipo: {type(exc).__name__}",
        f"Mensagem: {exc}",
    ]
    if safe_context:
        details_lines.append("Contexto: " + json.dumps(safe_context, ensure_ascii=False, sort_keys=True))
    if _log_path is not None:
        details_lines.append(f"Log: {_log_path}")
    details_lines.extend(("", "Rastreamento:", trace.rstrip()))
    details = "\n".join(details_lines)

    logger = logging.getLogger(LOGGER_NAME)
    logger.error(
        "error_id=%s stage=%s context=%s exception=%s",
        error_id,
        stage,
        json.dumps(safe_context, ensure_ascii=False, sort_keys=True),
        exc,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return ErrorReport(
        error_id=error_id,
        stage=str(stage),
        timestamp=timestamp,
        message=str(exc),
        log_path=_log_path,
        details=details,
    )


def install_exception_logging() -> None:
    """Log uncaught exceptions while preserving Python's normal hook."""

    previous_hook = sys.excepthook

    def _hook(exc_type, exc, tb):
        if isinstance(exc, KeyboardInterrupt):
            previous_hook(exc_type, exc, tb)
            return
        if exc.__traceback__ is None:
            exc = exc.with_traceback(tb)
        report_exception("uncaught", exc)
        previous_hook(exc_type, exc, tb)

    sys.excepthook = _hook


def _safe_context(context: dict[str, Any]) -> dict[str, str | int | float | bool | None]:
    safe: dict[str, str | int | float | bool | None] = {}
    for key, value in context.items():
        name = str(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[name] = value
        elif isinstance(value, Path):
            safe[name] = str(value)
        else:
            safe[name] = repr(value)[:500]
    return safe
