
import logging
import re
from api.services.sandbox import docker

logger = logging.getLogger(__name__)

def ensure_php_tag(code: str) -> str:
    """Ensure the code starts with <?php if it's meant to be a PHP file."""
    if code and not code.strip().startswith("<?php"):
        return f"<?php\n\n{code.strip()}"
    return code

async def write_file(container, path: str, content: str) -> None:
    """Write content to a file inside the container. Auto-injects <?php for .php files."""
    if path.endswith(".php"):
        content = ensure_php_tag(content)
    await docker.copy_file(container, path, content)

async def read_file(container, path: str) -> str:
    """Read file content from the container."""
    res = await docker.execute(container, f"cat {path}", timeout=5)
    return res.stdout

async def lint_php(container, path: str) -> tuple[bool, str]:
    """Check PHP syntax for a specific file."""
    res = await docker.execute(container, f"php -l {path}", timeout=15)
    return res.exit_code == 0, res.stderr or res.stdout

def prepare_pest_test(test_code: str, target_fqcn: str) -> str:
    """Inject required imports and covers() directive into a Pest test."""
    if not test_code: return ""
    
    # Ensure <?php is present for search/replace to work
    if not test_code.strip().startswith("<?php"):
        test_code = "<?php\n\n" + test_code.strip()

    # Auto-inject covers if missing
    if "covers(" not in test_code:
        fqcn = target_fqcn if target_fqcn.startswith("\\") else "\\" + target_fqcn
        test_code = test_code.replace("<?php", f"<?php\ncovers({fqcn}::class);")
        
    # Remove any existing individual or grouped Pest\Laravel helper imports to avoid duplicate/missing declarations
    test_code = re.sub(r'use\s+function\s+Pest\\Laravel\\(?:getJson|postJson|putJson|patchJson|deleteJson|get|post|put|patch|delete)\s*;', '', test_code)
    test_code = re.sub(r'use\s+function\s+Pest\\Laravel\\\{[^}]*\}\s*;', '', test_code)
    
    # Prepend the complete set of Laravel helper function imports
    imports = "use function Pest\\Laravel\\{get,post,put,patch,delete,getJson,postJson,putJson,patchJson,deleteJson};"
    test_code = test_code.replace("<?php", f"<?php\n{imports}")
        
    return test_code
