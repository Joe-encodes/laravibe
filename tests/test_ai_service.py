
import pytest
import re
from api.services.ai_service import (
    _parse_xml_response, _sanitize_php, _extract_json_object, 
    AIServiceError, PatchSpec
)

def test_parse_xml_no_code_corruption():
    # Hardening fix: html.unescape should not touch code content
    raw = """
    <repair>
      <file action="full_replace" path="app/Test.php">
      <?php
      $x = "&amp;"; 
      if ($y < 10 && $z > 5) return true;
      ?>
      </file>
    </repair>
    """
    resp = _parse_xml_response(raw)
    code = resp.patches[0].replacement
    # It should preserve &amp; and the < > symbols
    assert "&amp;" in code
    assert "< 10 &&" in code
    assert "$x" in code

def test_parse_xml_prose_only_escalation():
    # Hardening fix: Prose-only responses should trigger PARSING_FAILED
    raw = "I have analyzed the code and it seems you are missing a semicolon."
    resp = _parse_xml_response(raw)
    assert resp.thought_process == "PARSING_FAILED"
    assert "CRITICAL" in resp.diagnosis

def test_sanitize_php_migration_scoping():
    # Hardening fix: Only sanitize migrations in migration paths
    code = "class CreateUsersTable extends Migration { public function up() {} }"
    
    # Path with 'migration' -> should sanitize
    fixed_mig = _sanitize_php(code, "database/migrations/2023_01_01_create_users.php")
    assert "return new class extends Migration" in fixed_mig
    
    # Path without 'migration' -> should NOT sanitize
    fixed_reg = _sanitize_php("class UserController extends Controller {}", "app/Http/Controllers/UserController.php")
    assert "class UserController" in fixed_reg
    assert "return new class" not in fixed_reg

def test_parse_xml_malformed_tags():
    # Test recovery when tags are slightly broken or mixed
    raw = """
    <repair>
      <diagnosis>Fixed it</diagnosis>
      <file path="app/Test.php" action="full_replace">
      <?php echo "ok"; ?>
      </file>
    </repair>
    """
    resp = _parse_xml_response(raw)
    assert resp.diagnosis == "Fixed it"
    assert len(resp.patches) == 1
    assert resp.patches[0].target == "app/Test.php"

def test_parse_xml_empty_tags():
    raw = "<repair></repair>"
    resp = _parse_xml_response(raw)
    assert resp.thought_process == "PARSING_FAILED"

def test_sanitize_php_literal_newlines():
    # Model output literal \n instead of real newlines
    code = "<?php\\necho 'hi';\\n"
    sanitized = _sanitize_php(code)
    assert sanitized == "<?php\necho 'hi';\n"
