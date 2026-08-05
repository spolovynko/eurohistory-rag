"""Tests for configure_logging.

These touch the one genuinely global object in the process -- the root logger --
so every test here runs behind a fixture that puts it back. Without that, a test
that configures logging would silently disable caplog for every test after it.
"""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from eurohistory_rag.core.logging import NOISY_LIBRARIES, configure_logging


@pytest.fixture(autouse=True)
def isolate_root_logger() -> Iterator[None]:
    """Hand each test an empty root logger and restore the real one after."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_library_levels = {
        name: logging.getLogger(name).level for name in NOISY_LIBRARIES
    }

    # Detached, not closed: pytest's own capture handlers live in this list and
    # must survive. configure_logging closes whatever it finds, so they leave.
    root.handlers = []
    try:
        yield
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            # Windows will not delete tmp_path while the file is still open.
            handler.close()
        root.handlers = saved_handlers
        root.setLevel(saved_level)
        for name, level in saved_library_levels.items():
            logging.getLogger(name).setLevel(level)


def test_file_records_debug_while_the_console_stays_at_info(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole point of the file: it keeps what stderr filtered out."""
    log_file = tmp_path / "eurohistory.log"
    configure_logging(log_file=log_file)

    logging.getLogger("eurohistory_rag.example").debug("only in the file")

    assert "only in the file" in log_file.read_text(encoding="utf-8")
    assert "only in the file" not in capsys.readouterr().err


def test_verbose_puts_debug_on_the_console(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--verbose lowers the console handler, not the file handler."""
    configure_logging(verbose=True, log_file=tmp_path / "eurohistory.log")

    logging.getLogger("eurohistory_rag.example").debug("on screen too")

    assert "on screen too" in capsys.readouterr().err


def test_info_reaches_both_destinations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The normal case: an INFO line is watched live and kept."""
    log_file = tmp_path / "eurohistory.log"
    configure_logging(log_file=log_file)

    logging.getLogger("eurohistory_rag.example").info("both places")

    assert "both places" in capsys.readouterr().err
    assert "both places" in log_file.read_text(encoding="utf-8")


def test_configuring_twice_does_not_duplicate_records(tmp_path: Path) -> None:
    """Handlers are replaced, not accumulated -- one call, one line."""
    log_file = tmp_path / "eurohistory.log"
    configure_logging(log_file=log_file)
    configure_logging(log_file=log_file)

    logging.getLogger("eurohistory_rag.example").info("said once")

    assert log_file.read_text(encoding="utf-8").count("said once") == 1


def test_the_log_directory_is_created(tmp_path: Path) -> None:
    """A first run on a fresh checkout has no logs/ directory yet."""
    log_file = tmp_path / "does" / "not" / "exist" / "eurohistory.log"
    configure_logging(log_file=log_file)

    logging.getLogger("eurohistory_rag.example").info("made the path")

    assert log_file.exists()


def test_no_file_is_written_when_log_file_is_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The opt-out still logs to stderr; it only drops the file handler."""
    configure_logging(log_file=None)

    logging.getLogger("eurohistory_rag.example").info("stderr only")

    assert "stderr only" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_noisy_libraries_are_pinned_to_warning(tmp_path: Path) -> None:
    """httpx and friends log per request; at DEBUG they would fill the file."""
    configure_logging(verbose=True, log_file=tmp_path / "eurohistory.log")

    for name in NOISY_LIBRARIES:
        assert logging.getLogger(name).level == logging.WARNING


def test_the_line_carries_the_logger_name(tmp_path: Path) -> None:
    """The module name is what makes a line traceable back to its source."""
    log_file = tmp_path / "eurohistory.log"
    configure_logging(log_file=log_file)

    logging.getLogger("eurohistory_rag.pipeline.bronze.ingest").info("named")

    line = log_file.read_text(encoding="utf-8").strip()
    assert "INFO" in line
    assert "eurohistory_rag.pipeline.bronze.ingest: named" in line
