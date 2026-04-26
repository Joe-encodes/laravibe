"""
tests/test_patch_service.py — Unit tests for api/services/patch_service.py
No Docker, no AI, no network. Pure logic tests.
"""
import pytest
from api.services.patch_service import apply, PatchApplicationError
from api.services.ai_service import PatchSpec


def _patch(action="replace", target=None, replacement="", filename=None):
    return PatchSpec(action=action, target=target, replacement=replacement, filename=filename)


class TestFullReplace:
    def test_full_replace_success(self):
        code = "<?php\necho 'hello';\n"
        patch = _patch("full_replace", replacement="<?php\necho 'world';\n")
        result = apply(code, patch)
        assert "echo 'world';" in result
        assert "echo 'hello';" not in result

    def test_full_replace_empty_raises(self):
        patch = _patch("full_replace", replacement="")
        with pytest.raises(PatchApplicationError, match="replacement content is empty"):
            apply("<?php echo 'hi';", patch)

    def test_full_replace_strips_markdown_fences(self):
        code = "<?php\nfunction old() {}\n"
        patch = _patch("full_replace", replacement="```php\n<?php\nfunction new() {}\n```")
        result = apply(code, patch)
        assert "function new() {}" in result
        assert "```" not in result


class TestLegacyActions:
    def test_replace_raises_error(self):
        patch = _patch("replace", target="x", replacement="y")
        with pytest.raises(PatchApplicationError, match="no longer permitted"):
            apply("<?php", patch)

    def test_append_raises_error(self):
        patch = _patch("append", replacement="y")
        with pytest.raises(PatchApplicationError, match="no longer permitted"):
            apply("<?php", patch)


class TestCreateFile:
    def test_create_file_returns_code_unchanged(self):
        code = "<?php echo 'original';"
        patch = _patch("create_file", replacement="<?php // new file", filename="NewModel.php")
        result = apply(code, patch)
        assert result == code


class TestUnknownAction:
    def test_unknown_action_raises(self):
        patch = _patch("delete", target="something", replacement="")
        with pytest.raises(PatchApplicationError, match="Unknown patch action"):
            apply("<?php", patch)
