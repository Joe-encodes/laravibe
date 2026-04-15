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
    def is_timeout(self) -> bool:
        return self.exit_code == 124

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
    return docker.from_env(timeout=60)


async def is_alive(container) -> bool:
    """Check if container is still running and healthy."""
    loop = asyncio.get_event_loop()

    def _check():
        try:
            container.reload()  # refresh container state
            return container.status == "running"
        except Exception:
            return False

    return await loop.run_in_executor(None, _check)


async def ping(container, retries: int = 3) -> bool:
    """
    Run a fast no-op command to ensure the container is responsive.
    Retries multiple times as WSL/Docker cold starts can be slow.
    """
    for attempt in range(retries):
        try:
            # Run 'php -v' as a health check with a more lenient 15s timeout
            result = await execute(container, "php -v", timeout=15)
            if result.exit_code == 0:
                if attempt > 0:
                    logger.info(f"[{container.short_id}] Sandbox responded on attempt {attempt + 1}")
                return True
        except Exception as e:
            logger.warning(f"[{container.short_id}] Ping attempt {attempt + 1} failed: {e}")
        
        if attempt < retries - 1:
            await asyncio.sleep(1) # short breather before retry

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
    await copy_file(container, "/submitted/code.php", code)


async def copy_file(container, dest_path: str, content: str) -> None:
    """Write `content` to `dest_path` inside the running container."""
    loop = asyncio.get_event_loop()

    def _copy():
        import pathlib
        # Build an in-memory tar archive
        content_bytes = content.encode("utf-8")
        tar_buffer = io.BytesIO()
        filename = pathlib.Path(dest_path).name
        
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            info = tarfile.TarInfo(name=filename)
            info.size = len(content_bytes)
            tar.addfile(info, io.BytesIO(content_bytes))
        tar_buffer.seek(0)

        # Ensure directory exists
        dest_dir = str(pathlib.Path(dest_path).parent)
        container.exec_run(f"mkdir -p {dest_dir}", user="root")
        
        # put_archive needs the target directory
        container.put_archive(dest_dir, tar_buffer.getvalue())
        logger.debug(f"[{container.short_id}] File copied to {dest_path}")

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

        # Check if container is still alive before stopping it
        if await is_alive(container):
            logger.info(f"[{container.short_id}] Container still alive after timeout - keeping it running for next command")
            return ExecResult(
                stdout="",
                stderr=f"[TIMEOUT] Command exceeded {timeout}s limit but container remains healthy.",
                exit_code=124,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        else:
            logger.warning(f"[{container.short_id}] Container is NOT alive after timeout - reporting as crash")
            return ExecResult(
                stdout="",
                stderr="[CRASH] The container stopped or died during command execution.",
                exit_code=137, # Standard Docker exit code for SIGKILL/Death
                duration_ms=int((time.monotonic() - start) * 1000),
            )
    except Exception as exc:
        # Catch requests.exceptions.ReadTimeout or other Docker SDK issues
        duration_ms = int((time.monotonic() - start) * 1000)
        err_msg = f"Docker engine error: {exc}"
        logger.error(f"[{container.short_id}] {err_msg} (after {duration_ms}ms)")
        return ExecResult(
            stdout="",
            stderr=f"[SYSTEM_ERROR] {err_msg}",
            exit_code=500,  # Generic internal error code
            duration_ms=duration_ms,
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
