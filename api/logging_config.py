import logging
import logging.handlers
import pathlib
import sys
from contextvars import ContextVar

_submission_id_ctx: ContextVar[str] = ContextVar("submission_id", default="Global")


def set_submission_id(value: str):
    """Bind submission id to current async context."""
    return _submission_id_ctx.set(value)


def reset_submission_id(token) -> None:
    """Reset submission id context for current async task."""
    _submission_id_ctx.reset(token)

def setup_logging(debug: bool = False):
    """
    Set up a unified logging system that outputs to both console and file.
    Captures app logs and Uvicorn server logs.
    """
    log_dir = pathlib.Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "repair_platform.log"

    # 1. Base formatters
    # include submission_id if present (via LoggerAdapter)
    log_format = "%(asctime)s | %(levelname)-7s | %(name)-25s | [%(submission_id)s] %(message)s"
    
    # Custom formatter to handle missing 'submission_id' gracefully
    class ContextFormatter(logging.Formatter):
        def format(self, record):
            if not hasattr(record, "submission_id"):
                record.submission_id = "Global"
            return super().format(record)

    class SubmissionContextFilter(logging.Filter):
        def filter(self, record):
            if not hasattr(record, "submission_id"):
                val = _submission_id_ctx.get()
                record.submission_id = str(val) if val is not None else "Global"
            return True

    formatter = ContextFormatter(log_format)

    # 2. Handlers
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    console_handler.addFilter(SubmissionContextFilter())

    # Rotating file handler (10MB per file, keep 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)  # Always log DEBUG to file for audits
    file_handler.addFilter(SubmissionContextFilter())

    # 3. Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)
    
    # Clear existing handlers to prevent duplicates during reloads
    root_logger.handlers = []
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # 4. Redirect specific loggers
    # Silence some noisy 3rd party loggers
    logging.getLogger("docker").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    # Ensure Uvicorn logs go through our root logger handlers
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging_logger = logging.getLogger(logger_name)
        logging_logger.handlers = []
        logging_logger.propagate = True

    logging.info(f"Logging initialized. File: {log_file}")
