
"""
api/services/patch_service.py — Container-side code persistence with security guards.

Security model:
  - FORBIDDEN_FILES: filenames the AI must never overwrite
  - FORBIDDEN_DIRS:  directories that are off-limits
  - Path normalisation via posixpath.normpath blocks traversal (../../../.env)
  - PHP syntax is verified in /tmp before writing to the real destination

Failure policy:
  - Per-patch failures are logged and recorded but DO NOT abort remaining patches.
  - Only a complete write failure raises PatchApplicationError.
"""
import logging
import posixpath
import secrets
from typing import Dict, List

import api.services.sandbox as sandbox
from api.services.sandbox import docker

logger = logging.getLogger(__name__)

FORBIDDEN_FILES = {
    ".env", "composer.json", "composer.lock",
    "artisan", "package.json", "phpunit.xml", "pest.php",
}

FORBIDDEN_DIRS = {
    "vendor/", "node_modules/", "storage/", "bootstrap/cache/",
}


class PatchApplicationError(Exception):
    """Raised only when every patch in a batch failed — nothing was written."""
    pass


async def apply_all(container_id: str, patches: List) -> Dict[str, bool]:
    """
    Apply a list of PatchSpec patches to the sandbox container.

    Returns a dict mapping filename → True/False (success/failure).
    Individual patch failures do NOT raise; only a total-failure raises.
    """
    results: dict[str, bool] = {}
    container = sandbox.get_container(container_id)

    for patch in patches:
        filename = patch.filename or patch.target
        if not filename:
            logger.warning("[Patch] Skipping patch with no filename/target.")
            continue

        # ── Security: normalize and validate path ────────────────────────────
        safe_path = posixpath.normpath(filename).lstrip("/")

        if (
            any(safe_path.endswith(f) for f in FORBIDDEN_FILES)
            or any(safe_path.startswith(d) for d in FORBIDDEN_DIRS)
            or ".." in safe_path
        ):
            logger.error(f"[Patch] BLOCKED forbidden path: {filename!r}")
            results[filename] = False
            continue

        # ── Lint in /tmp before touching the real destination ────────────────
        tmp_path = f"/tmp/lint_{secrets.token_hex(8)}.php"
        try:
            await sandbox.write_file(container, tmp_path, patch.replacement)
            lint_ok, lint_msg = await sandbox.lint_php(container, tmp_path)

            if not lint_ok:
                logger.error(f"[Patch] Lint failed for {filename!r}: {lint_msg}")
                results[filename] = False
                continue  # skip this file, try the next patch

            # ── Write to real destination ────────────────────────────────────
            await sandbox.write_file(container, filename, patch.replacement)
            logger.info(f"[Patch] Applied {patch.action!r} → {filename!r}")
            results[filename] = True

        except Exception as exc:
            logger.error(f"[Patch] Write failed for {filename!r}: {exc}")
            results[filename] = False
            
        finally:
            await docker.execute(container, f"rm -f {tmp_path}")

    if results and not any(results.values()):
        raise PatchApplicationError(
            f"Every patch failed to apply: {list(results.keys())}"
        )

    return results
