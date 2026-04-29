"""
tests/test_ai_service.py — Unit tests for XML parsing and AI role logic.
"""
import pytest
from api.services.ai_service import (
    _parse_xml_response, _sanitize_php, _extract_json_object, 
    AIServiceError, PatchSpec
)

def test_parse_xml_response_basic():
    raw = """
    Prose before XML...
    <repair>
      <thought_process>I fixed it.</thought_process>
      <diagnosis>Missing semicolon</diagnosis>
      <fix>Added semicolon</fix>
      <file action="full_replace" path="app/Controller.php">
<?php
echo "fixed";
      </file>
      <pest_test>
<?php
it('works');
      </pest_test>
    </repair>
    Prose after XML.
    """
    resp = _parse_xml_response(raw)
    assert resp.diagnosis == "Missing semicolon"
    assert resp.fix_description == "Added semicolon"
    assert len(resp.patches) == 1
    assert resp.patches[0].target == "app/Controller.php"
    assert "echo \"fixed\";" in resp.patches[0].replacement
    assert "it('works');" in resp.pest_test


def test_parse_xml_response_multiple_files():
    raw = """
    <repair>
      <file action="create_file" path="app/Models/User.php">
<?php class User {}
      </file>
      <file action="full_replace" path="app/Http/Kernel.php">
<?php class Kernel {}
      </file>
    </repair>
    """
    resp = _parse_xml_response(raw)
    assert len(resp.patches) == 2
    assert resp.patches[0].action == "create_file"
    assert resp.patches[0].target == "app/Models/User.php"
    assert resp.patches[1].action == "full_replace"


def test_sanitize_php_newlines():
    # Model output literal \n instead of real newlines
    code = "<?php\\necho 'hi';\\n"
    sanitized = _sanitize_php(code)
    assert sanitized == "<?php\necho 'hi';\n"


def test_sanitize_php_anonymous_migration():
    code = """<?php
class CreateUsersTable extends Migration {
    public function up() {}
}
"""
    sanitized = _sanitize_php(code)
    assert "return new class extends Migration" in sanitized
    assert "class CreateUsersTable" not in sanitized


def test_extract_json_object():
    raw = """
    Prose...
    {
        "key": "value",
        "nested": { "a": 1 }
    }
    More prose...
    """
    json_str = _extract_json_object(raw)
    assert json_str == '{\n        "key": "value",\n        "nested": { "a": 1 }\n    }'


def test_extract_json_object_with_think():
    raw = """
    <think>
    Thinking...
    </think>
    ```json
    { "status": "ok" }
    ```
    """
    json_str = _extract_json_object(raw)
    assert json_str == '{ "status": "ok" }'


def test_extract_json_object_unbalanced():
    with pytest.raises(ValueError, match="Unbalanced braces"):
        _extract_json_object("{ 'a': 1")


def test_parse_xml_response_with_cdata():
    raw = """
    <repair>
      <file action="full_replace" path="app/Test.php">
<![CDATA[
<?php echo "CDATA works"; ?>
]]>
      </file>
    </repair>
    """
    resp = _parse_xml_response(raw)
    assert 'echo "CDATA works";' in resp.patches[0].replacement


def test_parse_xml_response_malformed_recovery():
    # Test that we can still get thought/diagnosis even if <file> is missing or malformed
    raw = """
    <repair>
      <thought_process>Thinking</thought_process>
      <diagnosis>Bug</diagnosis>
      <file action="invalid">
    </repair>
    """
    resp = _parse_xml_response(raw)
    assert resp.thought_process == "Thinking"
    assert resp.diagnosis == "Bug"
    assert len(resp.patches) == 0


def test_parse_xml_response_with_think_tag():
    # DeepSeek R1 often includes <think> tags outside <repair>
    raw = """
    <think>I should fix this by adding a model.</think>
    <repair>
      <diagnosis>Missing Model</diagnosis>
      <file action="create_file" path="app/Models/New.php">
<?php class New {}
      </file>
    </repair>
    """
    resp = _parse_xml_response(raw)
    assert resp.diagnosis == "Missing Model"
    assert len(resp.patches) == 1
