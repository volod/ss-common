import io
import logging
import re
import subprocess
import sys
from collections.abc import Iterator

import pytest

from ss_kit import logging as kit_logging


@pytest.fixture(autouse=True)
def _restore_root() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    kit_logging.stop_logging()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)


def test_compact_formatter_sanitizes_non_ascii() -> None:
    formatter = kit_logging.CompactFormatter("%(name)s %(message)s")
    record = logging.LogRecord(
        name="pipeline.local",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Step \u2192 %s",
        args=("DINOv3 \u2192 EfficientViT \u00d72 \u2705 \u00e9",),
        exc_info=None,
    )
    assert formatter.format(record) == "local Step -> DINOv3 -> EfficientViT x2 [ok] ?"
    assert record.name == "pipeline.local"  # the original record is untouched

    mapping = logging.LogRecord("a", logging.INFO, __file__, 1, "%(k)s", None, None)
    mapping.args = {"k": "\u2014"}
    assert formatter.format(mapping) == "a --"
    assert kit_logging.ascii_log_text(7) == 7


def test_configure_logging_routes_through_one_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "debug")
    stream = io.StringIO()
    seen: list[str] = []

    class Counter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            seen.append(record.getMessage())
            return True

    assert kit_logging.configure_logging(stream=stream, filters=[Counter()], banner="Started")
    assert not kit_logging.configure_logging(stream=io.StringIO())
    assert logging.getLogger().level == logging.DEBUG

    kit_logging.get_logger("svc.module").debug("hello %s", "world")
    kit_logging.stop_logging()
    kit_logging.stop_logging()

    lines = stream.getvalue().splitlines()
    assert re.fullmatch(r"Started: \d{4}-\d\d-\d\d \d\d:\d\d:\d\d", lines[0])
    assert re.fullmatch(r"\d\d:\d\d,\d{3} DEBUG module hello world", lines[1])
    assert seen == ["hello world"]


def test_force_replaces_the_configuration() -> None:
    first, second = io.StringIO(), io.StringIO()
    kit_logging.configure_logging("INFO", stream=first)
    assert kit_logging.configure_logging(logging.WARNING, stream=second, force=True)
    logging.getLogger("x").warning("to second")
    kit_logging.stop_logging()  # drains the queue before the raw footer
    kit_logging.write_line("raw line")
    assert first.getvalue() == ""
    assert second.getvalue().endswith(" WARNING x to second\nraw line\n")
    assert logging.getLogger().handlers == []


def test_import_and_get_logger_write_nothing() -> None:
    probe = (
        "import logging, ss_kit.logging as kl;"
        "kl.get_logger('quiet').warning('unconfigured');"
        "assert not logging.getLogger().handlers"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    # Python's last-resort handler prints the warning; ss_kit installs nothing itself.
    assert result.stdout == ""
