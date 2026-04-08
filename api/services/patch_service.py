"""
api/services/patch_service.py — Apply AI-suggested patches to PHP code strings.

Handles three action types:
  - replace     find exact target string and replace it
  - append      add replacement at end of code
  - create_file signal to the repair loop to write a new file (returned as-is)
"""
import logging
import re

from api.services.ai_service import PatchSpec

logger = logging.getLogger(__name__)


class PatchApplicationError(Exception):
    """Raised when a patch cannot be applied cleanly."""
    pass


def strip_markdown_fences(code: str) -> str:
    """Strip ```php ... ``` or ``` ... ``` wrappers from AI output."""
    code = code.strip()
    # Match optional language identifier after opening fence
    pattern = r"^```[\w]*\n?(.*?)\n?```$"
    match = re.fullmatch(pattern, code, flags=re.DOTALL)
    if match:
        return match.group(1)
    return code


# Internal alias — keep using this inside this module
_strip_markdown_fences = strip_markdown_fences


def apply(current_code: str, patch: PatchSpec) -> str:
    """
    Apply the patch to current_code and return the new code string.
    create_file action returns current_code unchanged (caller handles the new file).
    Raises PatchApplicationError if replacement target is not found.
    """
    replacement = _strip_markdown_fences(patch.replacement)

    if patch.action == "replace":
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
        new_code = current_code.rstrip() + "\n\n" + replacement + "\n"
        logger.debug(f"[Patch] append: added {len(replacement)} chars to end")
        return new_code

    elif patch.action == "create_file":
        if not patch.filename:
            raise PatchApplicationError("Patch action='create_file' but no 'filename' provided.")
        logger.debug(f"[Patch] create_file: signalled for {patch.filename} — current_code unchanged, repair_service writes new file")
        # For create_file, repair_service reads patch.replacement directly to write the new file.
        # current_code stays unchanged — we are adding a dependency, not modifying the submitted code.
        return current_code

    else:
        raise PatchApplicationError(f"Unknown patch action: {patch.action!r}")
