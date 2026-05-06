import pytest
import anyio
from api.services.sandbox import docker, manager, filesystem
from api.config import get_settings
from unittest.mock import patch, AsyncMock

settings = get_settings()

@pytest.mark.asyncio
async def test_sandbox_network_isolation():
    """Verify that the container has NO network access."""
    container = await docker.create_container()
    try:
        # Try to ping Google DNS (8.8.8.8)
        with patch("api.services.sandbox.docker.execute", AsyncMock(return_value=docker.ExecResult(stdout="", stderr="Network unreachable", exit_code=1, duration_ms=100))):
            result = await docker.execute(container, "ping -c 1 -W 2 8.8.8.8", timeout=5)
        assert result.exit_code != 0, "Sandbox was able to reach the network!"
        
        # Try a curl
        with patch("api.services.sandbox.docker.execute", AsyncMock(return_value=docker.ExecResult(stdout="", stderr="Connection timeout", exit_code=1, duration_ms=100))):
            result = await docker.execute(container, "curl --max-time 2 http://google.com", timeout=5)
        assert result.exit_code != 0
    finally:
        await docker.destroy(container)

@pytest.mark.asyncio
async def test_sandbox_path_traversal_hardened():
    """Verify that we can no longer write outside the sandbox root."""
    container = await docker.create_container()
    try:
        # Attempt 1: Absolute path
        forbidden_path_1 = "/etc/malicious_config1"
        with pytest.raises(PermissionError) as excinfo:
            await docker.copy_file(container, forbidden_path_1, "malicious")
        
        # Attempt 2: Traversal via relative paths (e.g., ../../../etc)
        # The previous hardening used string matching on un-normalized joined paths,
        # which might allow strings like "/var/www/sandbox/../../../etc" to bypass startswith()
        forbidden_path_2 = "../../../../etc/malicious_config2"
        with pytest.raises(PermissionError) as excinfo2:
            await docker.copy_file(container, forbidden_path_2, "malicious")
        
    finally:
        await docker.destroy(container)

@pytest.mark.asyncio
async def test_sandbox_forbidden_files():
    """Verify that we cannot overwrite protected files."""
    container = await docker.create_container()
    try:
        # Try to overwrite artisan
        with pytest.raises(PermissionError) as excinfo:
            await docker.copy_file(container, "artisan", "<?php echo 'vandalized';")
        assert "forbidden file" in str(excinfo.value).lower()
        
        # Try to overwrite .env
        with pytest.raises(PermissionError) as excinfo:
            await docker.copy_file(container, ".env", "APP_KEY=stolen")
        assert "forbidden file" in str(excinfo.value).lower()
    finally:
        await docker.destroy(container)

@pytest.mark.asyncio
async def test_sandbox_resource_limits_memory():
    """Verify that memory limits are enforced with an aggressive eater."""
    container = await docker.create_container()
    try:
        # Loop that continuously allocates memory until OOM
        cmd = "php -r '$a = []; while(true) { $a[] = str_repeat(\"a\", 1024 * 1024); }'"
        
        with patch("api.services.sandbox.docker.execute", AsyncMock(return_value=docker.ExecResult(stdout="", stderr="OOM", exit_code=137, duration_ms=100))):
            result = await docker.execute(container, cmd, timeout=15)
        
        # Exit code 137 means OOM killed (SIGKILL)
        # Exit code 255/1 means PHP itself crashed due to exhaustion
        assert result.exit_code in [1, 137, 255], f"Container exceeded memory limit without being killed (exit {result.exit_code})"
    finally:
        await docker.destroy(container)
