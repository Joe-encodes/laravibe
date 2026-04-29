
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from api.services.patch_service import apply_all, PatchApplicationError
from api.services.ai_service import PatchSpec


def _patch(action="full_replace", target="app/Test.php", replacement="<?php", filename=None):
    return PatchSpec(action=action, target=target, replacement=replacement, filename=filename or target)


@pytest.mark.asyncio
async def test_apply_all_success():
    patches = [_patch()]
    container = MagicMock()
    with (
        patch("api.services.sandbox.get_container", return_value=container),
        patch("api.services.sandbox.write_file", AsyncMock()),
        patch("api.services.sandbox.lint_php", AsyncMock(return_value=(True, "No syntax errors detected"))),
    ):
        results = await apply_all("container-123", patches)
        assert results["app/Test.php"] is True


@pytest.mark.asyncio
async def test_apply_forbidden_file():
    """Forbidden files must be blocked; since the whole batch fails, raises PatchApplicationError."""
    patches = [_patch(target=".env", filename=".env")]
    container = MagicMock()
    with (
        patch("api.services.sandbox.get_container", return_value=container),
    ):
        with pytest.raises(PatchApplicationError):
            await apply_all("container-123", patches)


@pytest.mark.asyncio
async def test_apply_forbidden_dir():
    """Forbidden directories must be blocked and raise when it's the only patch."""
    patches = [_patch(target="vendor/malicious.php", filename="vendor/malicious.php")]
    container = MagicMock()
    with (
        patch("api.services.sandbox.get_container", return_value=container),
    ):
        with pytest.raises(PatchApplicationError):
            await apply_all("container-123", patches)


@pytest.mark.asyncio
async def test_apply_path_traversal():
    """Path traversal must be blocked and raise when it's the only patch."""
    patches = [_patch(target="app/../../../.env", filename="app/../../../.env")]
    container = MagicMock()
    with (
        patch("api.services.sandbox.get_container", return_value=container),
    ):
        with pytest.raises(PatchApplicationError):
            await apply_all("container-123", patches)


@pytest.mark.asyncio
async def test_apply_partial_failure():
    """When one patch fails and another succeeds, no exception is raised."""
    patches = [
        _patch(target=".env", filename=".env"),         # blocked
        _patch(target="app/Good.php", filename="app/Good.php"),  # should pass
    ]
    container = MagicMock()
    with (
        patch("api.services.sandbox.get_container", return_value=container),
        patch("api.services.sandbox.write_file", AsyncMock()),
        patch("api.services.sandbox.lint_php", AsyncMock(return_value=(True, "OK"))),
    ):
        results = await apply_all("container-123", patches)
        assert results[".env"] is False
        assert results["app/Good.php"] is True


@pytest.mark.asyncio
async def test_apply_lint_failure():
    """A lint failure on the only patch should raise PatchApplicationError."""
    patches = [_patch(replacement="<?php invalid{{")]
    container = MagicMock()
    with (
        patch("api.services.sandbox.get_container", return_value=container),
        patch("api.services.sandbox.write_file", AsyncMock()),
        patch("api.services.sandbox.lint_php", AsyncMock(return_value=(False, "Parse error: syntax error"))),
    ):
        with pytest.raises(PatchApplicationError):
            await apply_all("container-123", patches)
