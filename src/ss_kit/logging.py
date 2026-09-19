"""Compact, ASCII-only, thread-safe logging for the ss services.

Importing this module configures nothing and writes nothing. A service entrypoint calls
`configure_logging()` once; it routes every record through a queue to one stderr handler, so
concurrent threads never interleave lines, and formats records as `mm:ss,mmm LEVEL leaf message`.
The optional `banner` is written once with the full date so relative timestamps stay anchored.
"""

import atexit
import datetime
import logging
import logging.handlers
import os
import queue
import sys
from collections.abc import Iterable
from typing import TextIO

LOG_LEVEL_ENV = "LOG_LEVEL"
DEFAULT_LEVEL = "INFO"
DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Typographic characters (by code point) that commonly reach log messages, with their ASCII
# spelling: arrows, dashes, ellipsis, math signs, bullets, and check marks.
_ASCII_REPLACEMENTS = str.maketrans(
    {
        0x2192: "->",
        0x2190: "<-",
        0x2194: "<->",
        0x2014: "--",
        0x2013: "-",
        0x2026: "...",
        0x00D7: "x",
        0x2265: ">=",
        0x2264: "<=",
        0x2248: "~",
        0x00B7: "-",
        0x2022: "-",
        0x2713: "[ok]",
        0x2705: "[ok]",
        0x2717: "[x]",
        0x2193: "down ",
    }
)


def ascii_log_text(value: object) -> object:
    """ASCII spelling of a string (other characters become `?`); non-strings pass through."""
    if not isinstance(value, str):
        return value
    return value.translate(_ASCII_REPLACEMENTS).encode("ascii", "replace").decode("ascii")


class CompactFormatter(logging.Formatter):
    """`mm:ss,mmm LEVEL leaf_name message`, ASCII only; the record itself is not mutated."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        created = datetime.datetime.fromtimestamp(record.created)
        return f"{created.minute:02d}:{created.second:02d},{created.microsecond // 1000:03d}"

    def format(self, record: logging.LogRecord) -> str:
        copy = logging.makeLogRecord(record.__dict__)
        copy.name = record.name.split(".")[-1]
        copy.msg = ascii_log_text(copy.msg)
        if isinstance(copy.args, dict):
            copy.args = {key: ascii_log_text(value) for key, value in copy.args.items()}
        elif copy.args:
            copy.args = tuple(ascii_log_text(arg) for arg in copy.args)
        return super().format(copy)


class _State:
    listener: logging.handlers.QueueListener | None = None
    queue_handler: logging.Handler | None = None
    sink: logging.StreamHandler[TextIO] | None = None
    atexit_registered = False


def is_configured() -> bool:
    return _State.listener is not None


def stop_logging() -> None:
    """Drain queued records to the sink and detach the queue handler (idempotent)."""
    listener, handler = _State.listener, _State.queue_handler
    _State.listener = _State.queue_handler = None
    if listener is not None:
        listener.stop()
    if handler is not None:
        logging.getLogger().removeHandler(handler)


def write_line(text: str) -> None:
    """Write one raw line to the configured sink (stderr before configuration)."""
    stream = _State.sink.stream if _State.sink is not None else sys.stderr
    stream.write(f"{text}\n")
    stream.flush()


def configure_logging(
    level: str | int | None = None,
    *,
    stream: TextIO | None = None,
    filters: Iterable[logging.Filter] = (),
    banner: str | None = None,
    force: bool = False,
) -> bool:
    """Install the queue handler on the root logger; returns False when already configured.

    `level` defaults to `$LOG_LEVEL` (INFO). Handlers attached earlier by third-party imports
    are removed. `filters` run synchronously on the calling thread. With `force`, an existing
    configuration is stopped and replaced.
    """
    if is_configured():
        if not force:
            return False
        stop_logging()
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    sink: logging.StreamHandler[TextIO] = logging.StreamHandler(stream or sys.stderr)
    sink.setFormatter(CompactFormatter(DEFAULT_FORMAT))
    log_queue: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
    queue_handler = logging.handlers.QueueHandler(log_queue)
    for log_filter in filters:
        queue_handler.addFilter(log_filter)
    listener = logging.handlers.QueueListener(log_queue, sink, respect_handler_level=True)
    listener.start()
    _State.listener, _State.queue_handler, _State.sink = listener, queue_handler, sink
    if not _State.atexit_registered:
        atexit.register(stop_logging)
        _State.atexit_registered = True

    root.addHandler(queue_handler)
    root.setLevel(_level_name(level))
    if banner:
        write_line(f"{banner}: {datetime.datetime.now().strftime(DATE_FORMAT)}")
    return True


def _level_name(level: str | int | None) -> str | int:
    if level is None:
        level = os.getenv(LOG_LEVEL_ENV, DEFAULT_LEVEL)
    return level.upper() if isinstance(level, str) else level


def get_logger(name: str) -> logging.Logger:
    """A named logger; never configures handlers (call `configure_logging` at startup)."""
    return logging.getLogger(name)
