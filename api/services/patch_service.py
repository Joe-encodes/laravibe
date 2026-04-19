"""
api/services/patch_service.py — Apply AI-suggested patches to PHP code strings.

Handles patch actions:
  - full_replace  replace the ENTIRE file with the given content (preferred/mandatory)
  - create_file   signal to the repair loop to write a new file (returned as-is)

Legacy actions (replace, append) are kept for backward compatibility.
"""
import logging
import re
from dataclasses import dataclass, field

from api.services.ai_service import PatchSpec

logger = logging.getLogger(__name__)

# Files the AI is not allowed to create or overwrite.
FORBIDDEN_FILENAMES = frozenset({
    "routes/api.php",
    "routes/web.php",
    "routes/console.php",
    "routes/channels.php",
})


class PatchApplicationError(Exception):
    """Raised when a patch cannot be applied cleanly."""
    pass


@dataclass
class ApplyAllResult:
    """Outcome of processing a full patches list."""
    updated_code: str
    created_files: dict[str, str] = field(default_factory=dict)  # rel_path → content
    actions_taken: list[str] = field(default_factory=list)
    skipped_forbidden: list[str] = field(default_factory=list)


def strip_markdown_fences(code: str) -> str:
    """Strip ```php ... ``` or ``` ... ``` wrappers from AI output."""
    code = code.strip()
    # Match optional language identifier after opening fence
    pattern = r"^```[\w]*\n?(.*?)\n?```$"
    match = re.fullmatch(pattern, code, flags=re.DOTALL)
    if match:
        return match.group(1)
    return code



def _is_forbidden_filename(filename: str) -> bool:
    """Check if a filename is in the forbidden list (normalizes slashes)."""
    normalized = filename.replace("\\", "/").strip("/")
    return normalized in FORBIDDEN_FILENAMES


def apply_all(current_code: str, patches: list[PatchSpec]) -> ApplyAllResult:
    """
    Process a list of patches in order.

    - full_replace patches update current_code.
    - create_file patches are collected into created_files for the caller.
    - Forbidden filenames are skipped with a warning (not an exception).

    Returns an ApplyAllResult with updated_code, created_files dict, and
    tracking lists.
    """
    result = ApplyAllResult(updated_code=current_code)

    for patch in patches:
        if patch.action == "create_file" and patch.filename and _is_forbidden_filename(patch.filename):
            logger.warning(f"[Patch] BLOCKED forbidden create_file target: {patch.filename}")
            result.skipped_forbidden.append(patch.filename)
            result.actions_taken.append(f"BLOCKED:{patch.filename}")
            continue

        new_code = apply(result.updated_code, patch)

        if patch.action == "create_file":
            assert patch.filename is not None, "create_file must have a filename"
            content = strip_markdown_fences(patch.replacement)
            result.created_files[patch.filename] = content
            result.actions_taken.append("create_file")
        else:
            result.updated_code = new_code
            result.actions_taken.append(patch.action)

    return result


def apply(current_code: str, patch: PatchSpec) -> str:
    """
    Apply a single patch to current_code and return the new code string.
    create_file action returns current_code unchanged (caller handles the new file).
    Raises PatchApplicationError if replacement target is not found.
    """
    replacement = strip_markdown_fences(patch.replacement)

    if patch.action == "full_replace":
        if not replacement:
            raise PatchApplicationError("Patch action='full_replace' but replacement content is empty.")
        logger.debug(f"[Patch] full_replace: rewrote entire file ({len(replacement)} chars)")
        return replacement

    elif patch.action == "replace":
        logger.warning("[Patch] AI used deprecated 'replace' action — should be 'full_replace'")
        if not patch.target:
            raise PatchApplicationError("Patch action='replace' but no 'target' string provided.")

        if patch.target not in current_code:
            raise PatchApplicationError(
                f"Patch target not found in code.\n"
                f"Target (first 200 chars): {patch.target[:200]!r}\n"
                f"Code (first 200 chars): {current_code[:200]!r}"
            )

        new_code = current_code.replace(patch.target, replacement, 1)
        logger.debug(f"[Patch] replace: swapped {len(patch.target)} chars → {len(replacement)} chars")
        return new_code

    elif patch.action == "append":
        logger.warning("[Patch] AI used deprecated 'append' action — should be 'full_replace'")
        new_code = current_code.rstrip() + "\n\n" + replacement + "\n"
        logger.debug(f"[Patch] append: added {len(replacement)} chars to end")
        return new_code

    elif patch.action == "create_file":
        if not patch.filename:
            raise PatchApplicationError("Patch action='create_file' but no 'filename' provided.")
        if _is_forbidden_filename(patch.filename):
            raise PatchApplicationError(
                f"FORBIDDEN: AI attempted to create/overwrite '{patch.filename}'. "
                f"Route files are managed by the sandbox."
            )
        logger.debug(f"[Patch] create_file: signalled for {patch.filename} — current_code unchanged")
        return current_code

    else:
        raise PatchApplicationError(f"Unknown patch action: {patch.action!r}")
