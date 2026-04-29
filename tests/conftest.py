"""
tests/conftest.py — Shared pytest fixtures for the repair platform test suite.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
# asyncio_mode=auto in pytest.ini handles the event loop — no custom fixture needed


# ── Fake ExecResult ────────────────────────────────────────────────────────────
@pytest.fixture
def ok_exec():
    """A successful docker exec result."""
    from api.services.sandbox.docker import ExecResult
    return ExecResult(stdout="Success!", stderr="", exit_code=0, duration_ms=100)


@pytest.fixture
def err_exec():
    """A failed docker exec result with PHP fatal error."""
    from api.services.sandbox.docker import ExecResult
    return ExecResult(
        stdout="",
        stderr="Fatal error: Class 'App\\Models\\Product' not found in /submitted/code.php on line 12",
        exit_code=255,
        duration_ms=80,
    )


# ── Fake container ─────────────────────────────────────────────────────────────
@pytest.fixture
def mock_container():
    """Mock docker container object."""
    container = MagicMock()
    container.short_id = "abc123de"
    container.exec_run = MagicMock(return_value=MagicMock(output=(b"ok", b""), exit_code=0))
    return container


# ── Sample PHP code fixtures ───────────────────────────────────────────────────
@pytest.fixture
def broken_php_missing_model():
    return open("tests/fixtures/missing_model.php").read()


@pytest.fixture
def broken_php_wrong_namespace():
    return open("tests/fixtures/wrong_namespace.php").read()


@pytest.fixture
def broken_php_missing_import():
    return open("tests/fixtures/missing_import.php").read()
