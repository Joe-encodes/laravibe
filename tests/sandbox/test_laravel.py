
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from api.services.sandbox.laravel import detect_class_info, place_code_in_laravel, ClassInfo, execute_code

@pytest.fixture
def mock_container():
    container = MagicMock()
    container.short_id = "abc123de"
    return container

@pytest.mark.asyncio
class TestLaravelSandbox:

    async def test_detect_class_info_standard(self, mock_container):
        """Case 1: Standard Laravel Controller detection."""
        with patch("api.services.sandbox.docker.execute") as mock_exec:
            mock_exec.side_effect = [
                AsyncMock(exit_code=0, stdout=""), # php -l
                AsyncMock(stdout="App\\Http\\Controllers"), # ns
                AsyncMock(stdout="UserController") # cls
            ]
            
            info = await detect_class_info(mock_container)
            
            assert info.classname == "UserController"
            assert info.clean_namespace == "App\\Http\\Controllers"
            assert info.dest_file == "/var/www/sandbox/app/Http/Controllers/UserController.php"
            assert info.fqcn == "App\\Http\\Controllers\\UserController"
            assert info.route_resource == "users"

    async def test_detect_class_info_custom_namespace(self, mock_container):
        """Case 2: Custom namespace outside App."""
        with patch("api.services.sandbox.docker.execute") as mock_exec:
            mock_exec.side_effect = [
                AsyncMock(exit_code=0, stdout=""), # php -l
                AsyncMock(stdout="My\\Custom\\Namespace"), # ns
                AsyncMock(stdout="Helper") # cls
            ]
            
            info = await detect_class_info(mock_container)
            assert info.clean_namespace == "My\\Custom\\Namespace"
            assert info.dest_file == "/var/www/sandbox/My/Custom/Namespace/Helper.php"

    async def test_detect_class_info_path_traversal_guard(self, mock_container):
        """Case 3: Malicious namespace should be caught by security guard."""
        with patch("api.services.sandbox.docker.execute") as mock_exec:
            mock_exec.side_effect = [
                AsyncMock(exit_code=0, stdout=""), # php -l
                AsyncMock(stdout="../../../etc"), # ns
                AsyncMock(stdout="Exploit") # cls
            ]
            
            info = await detect_class_info(mock_container)
            # Should fallback to default safe path
            assert info.dest_file.startswith("/var/www/sandbox/app/Http/Controllers/")

    async def test_place_code_in_laravel_success(self, mock_container):
        """Case 4: Code placement verification success."""
        info = ClassInfo(
            namespace="App/Http/Controllers",
            clean_namespace="App\\Http\\Controllers",
            classname="UserController",
            dest_file="/var/www/sandbox/app/Http/Controllers/UserController.php",
            fqcn="App\\Http\\Controllers\\UserController",
            route_resource="users"
        )
        with patch("api.services.sandbox.docker.execute", AsyncMock(return_value=AsyncMock(stdout="OK", exit_code=0))):
            success = await place_code_in_laravel(mock_container, info)
            assert success is True

    async def test_place_code_in_laravel_failure(self, mock_container):
        """Case 5: Code placement verification failure (e.g. syntax error in Tinker)."""
        info = ClassInfo("ns", "ns", "cls", "/path", "fqcn", "res")
        with patch("api.services.sandbox.docker.execute", AsyncMock(return_value=AsyncMock(stdout="ERR", exit_code=1))):
            success = await place_code_in_laravel(mock_container, info)
            assert success is False

    async def test_execute_code_already_loaded(self, mock_container):
        """Case 6: execute_code should skip require if class already exists."""
        with (
            patch("api.services.sandbox.docker.copy_code", AsyncMock()),
            patch("api.services.sandbox.docker.execute", AsyncMock(return_value=AsyncMock(stdout="[ALREADY_LOADED:UserController]", exit_code=0)))
        ):
            res = await execute_code(mock_container, "<?php class UserController {}")
            assert "[ALREADY_LOADED:UserController]" in res["output"]
            assert res["exit_code"] == 0
