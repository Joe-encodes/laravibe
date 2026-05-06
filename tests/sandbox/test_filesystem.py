
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from api.services.sandbox.filesystem import ensure_php_tag, write_file, read_file, lint_php, prepare_pest_test

def test_ensure_php_tag():
    assert ensure_php_tag("echo 1;") == "<?php\n\necho 1;"
    assert ensure_php_tag("<?php echo 1;") == "<?php echo 1;"
    assert ensure_php_tag("") == ""

@pytest.mark.asyncio
async def test_write_file_injects_tag():
    container = MagicMock()
    with patch("api.services.sandbox.docker.copy_file", AsyncMock()) as mock_copy:
        await write_file(container, "test.php", "echo 1;")
        mock_copy.assert_called_once()
        path, content = mock_copy.call_args[0][1:]
        assert content.startswith("<?php")

@pytest.mark.asyncio
async def test_read_file_calls_docker():
    container = MagicMock()
    with patch("api.services.sandbox.docker.execute", AsyncMock(return_value=MagicMock(stdout="content"))) as mock_exec:
        content = await read_file(container, "path/to/file")
        assert content == "content"
        assert "cat path/to/file" in mock_exec.call_args[0][1]

@pytest.mark.asyncio
async def test_lint_php_success():
    container = MagicMock()
    with patch("api.services.sandbox.docker.execute", AsyncMock(return_value=MagicMock(exit_code=0, stdout="No syntax errors", stderr=""))) as mock_exec:
        ok, msg = await lint_php(container, "file.php")
        assert ok is True
        assert "No syntax errors" in msg

def test_prepare_pest_test_injection():
    test_code = "<?php it('works');"
    prepared = prepare_pest_test(test_code, "App\\Models\\User")
    assert "covers(\\App\\Models\\User::class)" in prepared
    assert "use function Pest\\Laravel" in prepared

def test_prepare_pest_test_no_double_injection():
    test_code = "<?php covers(\\App\\Models\\User::class); it('works');"
    prepared = prepare_pest_test(test_code, "App\\Models\\User")
    # Should not add another covers()
    assert prepared.count("covers(") == 1
