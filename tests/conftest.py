import pytest
import pytest_asyncio
import asyncio
import sys
import types
import os
import uuid
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

# PRE-EMPTIVE ENV OVERRIDE: 
# Use a unique path in /tmp for EACH test session to avoid schema conflicts
db_path = os.path.join(tempfile.gettempdir(), f"laravibe_test_{uuid.uuid4().hex[:8]}.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
os.environ["MASTER_REPAIR_TOKEN"] = "test-token-safe-for-unit-tests"

# Reset api.database singletons and clear config cache
try:
    from api.config import get_settings
    get_settings.cache_clear()
    import api.database
    api.database._engine = None
    api.database._sessionmaker = None
except (ImportError, AttributeError):
    pass

# Mock setup_logging to do nothing to avoid file locks on /mnt/c during tests
mock_logging = types.ModuleType("api.logging_config")
mock_logging.setup_logging = MagicMock()
mock_logging.set_submission_id = MagicMock()
mock_logging.reset_submission_id = MagicMock()
sys.modules["api.logging_config"] = mock_logging

# Only mock docker if INTEGRATION mode is not explicitly enabled
USE_MOCK_DOCKER = os.getenv("INTEGRATION") != "1"

if USE_MOCK_DOCKER:
    # COMPLETELY mock docker module before any api.* imports
    mock_docker = types.ModuleType("docker")
    sys.modules["docker"] = mock_docker
    mock_docker.from_env = MagicMock()
    mock_docker.from_env.return_value = MagicMock()
    # Add DockerClient class for type hinting
    mock_docker.DockerClient = type("DockerClient", (), {})
    
    # Add models hierarchy
    mock_docker.models = types.ModuleType("docker.models")
    sys.modules["docker.models"] = mock_docker.models
    mock_docker.models.containers = types.ModuleType("docker.models.containers")
    sys.modules["docker.models.containers"] = mock_docker.models.containers
    mock_docker.models.containers.Container = type("Container", (), {})

    mock_docker_errors = types.ModuleType("docker.errors")
    sys.modules["docker.errors"] = mock_docker_errors
    mock_docker_errors.DockerException = type("DockerException", (Exception,), {})
    mock_docker_errors.NotFound = type("NotFound", (Exception,), {})
    mock_docker.errors = mock_docker_errors

    # Setup default client/container hierarchy
    mock_client = MagicMock()
    mock_docker.from_env.return_value = mock_client
    
    mock_container = MagicMock()
    mock_client.containers.run.return_value = mock_container
    
    # Ensure exec_run returns a result with .output (tuple) and .exit_code
    def default_exec_run(*args, **kwargs):
        res = MagicMock()
        res.exit_code = 0
        res.output = (b"", b"")
        return res
    
    mock_container.exec_run.side_effect = default_exec_run
else:
    mock_docker = None

@pytest.fixture(scope="session", autouse=True)
def mock_docker_global():
    if USE_MOCK_DOCKER:
        yield mock_docker
    else:
        yield None

@pytest_asyncio.fixture(autouse=True)
async def mock_destroy_sandbox():
    """Globally mock destroy_sandbox to prevent container deletion during tests."""
    if USE_MOCK_DOCKER:
        # Use string patching to avoid premature imports
        with patch("api.services.sandbox.manager.destroy_sandbox", new_callable=AsyncMock) as m:
            yield m
    else:
        yield None

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"

@pytest_asyncio.fixture(scope="session", autouse=True)
async def test_db_setup():
    """Initializes the database schema for the test session."""
    from api.database import Base, get_engine
    import api.models
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except:
            pass

@pytest_asyncio.fixture
async def db_session():
    """Yields a fresh session from the sessionmaker."""
    from api.database import get_sessionmaker
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        yield session
        await session.close()

@pytest_asyncio.fixture
async def client():
    """Yields an AsyncClient with database dependency overrides."""
    from httpx import AsyncClient, ASGITransport
    from api.main import app
    from api.database import get_db, get_sessionmaker
    
    async def _get_test_db():
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            yield session
            await session.close()
    
    app.dependency_overrides[get_db] = _get_test_db
    # Mock authentication to return a dummy user
    from api.routers.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"sub": "test-user", "role": "admin"}
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)

@pytest.fixture
def ok_exec():
    from api.services.sandbox.docker import ExecResult
    return ExecResult(stdout="Success!", stderr="", exit_code=0, duration_ms=100)
