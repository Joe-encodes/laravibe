"""
api/services/docker_service.py — Container lifecycle management via docker-py.

Responsibilities:
  - create_container()  spin up a fresh laravel-sandbox container
  - copy_code()         write PHP code to /submitted/code.php inside container
  - execute()           run a shell command, return stdout/stderr/exit_code
  - destroy()           stop + remove the container (always call in finally)
  - health_check()      confirm Docker daemon is reachable
"""
import asyncio
import io
import tarfile
import time
import logging
from dataclasses import dataclass

import docker
from docker.errors import DockerException, NotFound

from api.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int

    @property
    def has_php_fatal(self) -> bool:
        """PHP fatal errors don't always produce non-zero exit codes — check text too."""
        combined = (self.stdout + self.stderr).lower()
        return any(kw in combined for kw in [
            "fatal error", "parse error", "uncaught exception",
            "class not found", "undefined function", "call to undefined"
        ])


def _get_client() -> docker.DockerClient:
    """Return a Docker client. Raises DockerException if daemon unreachable."""
    return docker.from_env(timeout=30)


async def health_check() -> bool:
    """Return True if Docker daemon is reachable."""
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: _get_client().ping())
        return True
    except DockerException:
        return False


async def create_container() -> docker.models.containers.Container:
    """
    Spin up a fresh laravel-sandbox container with strict resource limits.
    Container has NO network access (--network=none) for security.
    Returns the container object (still running, waiting for commands).
    """
    loop = asyncio.get_event_loop()

    def _create():
        client = _get_client()
        container = client.containers.run(
            image=settings.docker_image_name,
            detach=True,
            network_mode="none",              # no network access from inside container
            mem_limit=settings.container_memory_limit,
            nano_cpus=int(settings.container_cpu_limit * 1e9),
            pids_limit=settings.container_pid_limit,
            read_only=False,                  # needs write access for composer / artisan
            security_opt=["no-new-privileges:true"],
            environment={
                "SANDBOX_DB_HOST": settings.sandbox_db_host,
                "SANDBOX_DB_PORT": str(settings.sandbox_db_port),
                "SANDBOX_DB_DATABASE": settings.sandbox_db_database,
                "SANDBOX_DB_USERNAME": settings.sandbox_db_username,
                "SANDBOX_DB_PASSWORD": settings.sandbox_db_password,
                "SANDBOX_REDIS_HOST": settings.sandbox_redis_host,
            },
            command="sleep infinity",         # keep alive until we exec into it
            remove=False,                     # we destroy manually in finally block
        )
        logger.info(f"Container created: {container.short_id}")
        return container

    return await loop.run_in_executor(None, _create)


async def copy_code(container, code: str) -> None:
    """Write `code` to /submitted/code.php inside the running container."""
    loop = asyncio.get_event_loop()

    def _copy():
        # Build an in-memory tar archive containing code.php
        code_bytes = code.encode("utf-8")
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            info = tarfile.TarInfo(name="code.php")
            info.size = len(code_bytes)
            tar.addfile(info, io.BytesIO(code_bytes))
        tar_buffer.seek(0)

        # Create /submitted/ directory and put the archive there
        container.exec_run("mkdir -p /submitted", user="root")
        container.put_archive("/submitted", tar_buffer.getvalue())
        logger.debug(f"[{container.short_id}] Code copied to /submitted/code.php")

    await loop.run_in_executor(None, _copy)


async def execute(
    container,
    command: str,
    timeout: int | None = None,
    user: str = "sandbox",
) -> ExecResult:
    """
    Run `command` inside the container.
    Returns ExecResult with stdout, stderr, exit_code, duration_ms.
    Kills container after `timeout` seconds if it hangs.
    """
    loop = asyncio.get_event_loop()
    timeout = timeout or settings.container_timeout_seconds
    start = time.monotonic()

    def _exec():
        result = container.exec_run(
            cmd=["bash", "-c", command],
            stdout=True,
            stderr=True,
            demux=True,          # separate stdout/stderr streams
            user=user,
        )
        stdout_bytes, stderr_bytes = result.output or (b"", b"")
        return (
            (stdout_bytes or b"").decode("utf-8", errors="replace"),
            (stderr_bytes or b"").decode("utf-8", errors="replace"),
            result.exit_code or 0,
        )

    try:
        stdout, stderr, exit_code = await asyncio.wait_for(
            loop.run_in_executor(None, _exec),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(f"[{container.short_id}] Command timed out after {timeout}s: {command}")
        await loop.run_in_executor(None, lambda: container.stop(timeout=2))
        return ExecResult(
            stdout="",
            stderr=f"[TIMEOUT] Command exceeded {timeout}s limit.",
            exit_code=124,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.debug(f"[{container.short_id}] exit={exit_code} | {duration_ms}ms | cmd: {command[:80]}")
    return ExecResult(stdout=stdout, stderr=stderr, exit_code=exit_code, duration_ms=duration_ms)


async def destroy(container) -> None:
    """Stop and remove the container. Always call this in a finally block."""
    loop = asyncio.get_event_loop()

    def _destroy():
        try:
            container.stop(timeout=3)
        except Exception:
            pass
        try:
            container.remove(force=True)
            logger.info(f"Container destroyed: {container.short_id}")
        except NotFound:
            pass  # already gone
        except Exception as exc:
            logger.warning(f"Could not remove container {container.short_id}: {exc}")

    await loop.run_in_executor(None, _destroy)
