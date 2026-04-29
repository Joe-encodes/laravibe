
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from api.services.sandbox.laravel import detect_class_info

@pytest.mark.asyncio
async def test_detect_class_info():
    """Verify that we can correctly parse PHP class metadata from the container."""
    container = AsyncMock()
    
    # Mock Docker execution for namespace and classname
    with patch("api.services.sandbox.docker.execute") as mock_exec:
        mock_exec.side_effect = [
            AsyncMock(exit_code=0, stdout=""), # lint
            AsyncMock(stdout="App\\Http\\Controllers"), # ns
            AsyncMock(stdout="UserController") # cls
        ]
        
        info = await detect_class_info(container)
        
        assert info.classname == "UserController"
        assert info.clean_namespace == "App\\Http\\Controllers"
        assert info.dest_file == "/var/www/sandbox/app/Http/Controllers/UserController.php"
        assert info.route_resource == "users"
