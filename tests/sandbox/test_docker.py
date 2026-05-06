
import pytest
import io
from unittest.mock import AsyncMock, MagicMock, patch
from api.services.sandbox.docker import create_container, copy_file, execute, destroy, ExecResult

@pytest.fixture
def mock_docker_client():
    with patch("api.services.sandbox.docker._get_client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client

@pytest.fixture
def mock_container():
    container = MagicMock()
    container.id = "test-container-id"
    container.short_id = "test-short"
    # Default return for exec_run to avoid unpacking errors
    container.exec_run.return_value = MagicMock(exit_code=0, output=(b"ok", b""))
    return container

@pytest.mark.asyncio
class TestDockerService:

    async def test_create_container_success(self, mock_docker_client):
        """Case 1: Successful container creation with correct limits from config/env."""
        from api.config import get_settings
        settings = get_settings()
        
        mock_docker_client.containers.run.return_value = MagicMock(id="new-id")
        
        container = await create_container()
        
        assert container.id == "new-id"
        mock_docker_client.containers.run.assert_called_once()
        _, kwargs = mock_docker_client.containers.run.call_args
        assert kwargs["mem_limit"] == settings.container_memory_limit
        assert kwargs["network_mode"] == "none"

    async def test_copy_file_enforces_cage(self, mock_container):
        """Case 2: copy_file must prevent writing outside the cage and ensure directory exists."""
        # We don't mock to_thread, we mock the container methods it calls
        mock_container.exec_run.return_value = MagicMock(exit_code=0, output=(b"", b""))
        
        await copy_file(mock_container, "app/Models/User.php", "content")
        
        # 1. Verify mkdir was called for the caged path
        mock_container.exec_run.assert_called()
        mkdir_cmd = mock_container.exec_run.call_args_list[0][0][0]
        assert "mkdir -p /var/www/sandbox/app/Models" in mkdir_cmd
        
        # 2. Verify put_archive was called
        mock_container.put_archive.assert_called_once()
        dest_dir, _ = mock_container.put_archive.call_args[0]
        assert dest_dir == "/var/www/sandbox/app/Models"

    async def test_execute_success(self, mock_container):
        """Case 3: Successful command execution returns ExecResult."""
        # demux=True means output is (stdout, stderr)
        mock_container.exec_run.return_value = MagicMock(
            exit_code=0, 
            output=(b"hello world", b"no errors")
        )
        
        res = await execute(mock_container, "echo hello")
        
        assert isinstance(res, ExecResult)
        assert res.stdout == "hello world"
        assert res.stderr == "no errors"
        assert res.exit_code == 0

    async def test_execute_timeout_handling(self, mock_container):
        """Case 4: Command timeout should return 124 exit code if container still alive."""
        # Mocking asyncio.wait_for to raise TimeoutError
        with patch("api.services.sandbox.docker.asyncio.wait_for", side_effect=TimeoutError()):
            with patch("api.services.sandbox.docker.is_alive", AsyncMock(return_value=True)):
                res = await execute(mock_container, "sleep 10", timeout=1)
                assert res.exit_code == 124
                assert "[TIMEOUT]" in res.stderr

    async def test_destroy_container(self, mock_container):
        """Case 5: Container destruction."""
        await destroy(mock_container)
        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once()

    async def test_copy_file_forbidden_path(self, mock_container):
        """Case 6: copy_file should raise PermissionError for forbidden files."""
        with pytest.raises(PermissionError, match="Security Block"):
            await copy_file(mock_container, ".env", "SECRET=123")
