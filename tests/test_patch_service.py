"""
tests/test_patch_service.py — Unit tests for api/services/patch_service.py
No Docker, no AI, no network. Pure logic tests.
"""
import pytest
from api.services.patch_service import apply, PatchApplicationError
from api.services.ai_service import PatchSpec


def _patch(action="replace", target=None, replacement="", filename=None):
    return PatchSpec(action=action, target=target, replacement=replacement, filename=filename)


class TestReplace:
    def test_simple_replace(self):
        code = "<?php\necho 'hello';\n"
        patch = _patch("replace", target="echo 'hello';", replacement="echo 'world';")
        result = apply(code, patch)
        assert "echo 'world';" in result
        assert "echo 'hello';" not in result

    def test_replace_strips_markdown_fences(self):
        code = "<?php\nfunction old() {}\n"
        patch = _patch("replace", target="function old() {}", replacement="```php\nfunction new() {}\n```")
        result = apply(code, patch)
        assert "function new() {}" in result
        assert "```" not in result

    def test_replace_target_not_found_raises(self):
        code = "<?php echo 'hi';"
        patch = _patch("replace", target="echo 'bye';", replacement="echo 'replaced';")
        with pytest.raises(PatchApplicationError, match="not found"):
            apply(code, patch)

    def test_replace_no_target_raises(self):
        patch = _patch("replace", target=None, replacement="something")
        with pytest.raises(PatchApplicationError, match="no 'target'"):
            apply("<?php echo 'hi';", patch)

    def test_only_first_occurrence_replaced(self):
        code = "<?php\necho 'x';\necho 'x';\n"
        patch = _patch("replace", target="echo 'x';", replacement="echo 'y';")
        result = apply(code, patch)
        assert result.count("echo 'y';") == 1
        assert result.count("echo 'x';") == 1


class TestAppend:
    def test_append_adds_to_end(self):
        code = "<?php\nclass Foo {}"
        patch = _patch("append", replacement="// appended")
        result = apply(code, patch)
        assert result.endswith("// appended\n")
        assert "class Foo {}" in result

    def test_append_strips_fences(self):
        code = "<?php\n"
        patch = _patch("append", replacement="```\n// new line\n```")
        result = apply(code, patch)
        assert "// new line" in result
        assert "```" not in result


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
