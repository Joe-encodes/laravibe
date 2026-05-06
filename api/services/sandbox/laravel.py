
import base64
import logging
import re
import shlex
from dataclasses import dataclass
from api.config import get_settings
from api.services.sandbox import docker

logger = logging.getLogger(__name__)
settings = get_settings()

@dataclass
class ClassInfo:
    """Metadata for the PHP class being repaired."""
    namespace: str
    clean_namespace: str
    classname: str
    dest_file: str
    fqcn: str
    route_resource: str

async def detect_class_info(container) -> ClassInfo:
    """Detect namespace and classname from /var/www/sandbox/submitted_code.php."""
    # Pre-lint to ensure valid detection
    await docker.execute(container, "php -l /var/www/sandbox/submitted_code.php", timeout=5)

    ns_cmd = "php -r '$c=@file_get_contents(\"/var/www/sandbox/submitted_code.php\"); if(preg_match(\"/namespace\\s+([^;\\s]+)/\",$c,$m)) echo trim($m[1]);'"
    cls_cmd = "php -r '$c=@file_get_contents(\"/var/www/sandbox/submitted_code.php\"); if(preg_match(\"/class\\s+(\\w+)/\",$c,$m)) echo $m[1];'"
    
    ns_res = await docker.execute(container, ns_cmd, timeout=5)
    cls_res = await docker.execute(container, cls_cmd, timeout=5)
    
    namespace = ns_res.stdout.strip().replace("\\\\", "\\").replace("\\", "/") or "App/Http/Controllers"
    classname = cls_res.stdout.strip() or "SubmittedClass"
    
    clean_ns = namespace.replace("/", "\\").strip("\\")
    import posixpath
    dest_path = ("app/" + clean_ns[4:].replace("\\", "/")) if clean_ns.startswith("App\\") else clean_ns.replace("\\", "/")
    dest_file = posixpath.normpath(f"/var/www/sandbox/{dest_path}/{classname}.php")
    
    # Security Check: Prevent namespace path traversal
    if not dest_file.startswith("/var/www/sandbox/"):
        logger.warning(f"Malicious or invalid namespace detected: {namespace}. Falling back.")
        dest_file = f"/var/www/sandbox/app/Http/Controllers/{classname}.php"
    
    resource = re.sub(r'Controller$', '', classname, flags=re.IGNORECASE).lower()
    
    return ClassInfo(
        namespace=namespace,
        clean_namespace=clean_ns,
        classname=classname,
        dest_file=dest_file,
        fqcn=f"{clean_ns}\\{classname}",
        route_resource=f"{resource}s" if resource else f"{classname.lower()}s"
    )

async def setup_sqlite(container) -> None:
    """Configure container for internal SQLite usage and ensure base classes exist."""
    sh_script = """#!/bin/bash
# 1. Setup SQLite
touch /var/www/sandbox/database/database.sqlite
chmod 666 /var/www/sandbox/database/database.sqlite
sed -i 's/DB_CONNECTION=.*/DB_CONNECTION=sqlite/' /var/www/sandbox/.env
sed -i 's|DB_DATABASE=.*|DB_DATABASE=/var/www/sandbox/database/database.sqlite|' /var/www/sandbox/.env
php /var/www/sandbox/artisan migrate --force

# 2. Ensure base Controller exists (Laravel 11 might not have it)
mkdir -p /var/www/sandbox/app/Http/Controllers
if [ ! -f /var/www/sandbox/app/Http/Controllers/Controller.php ]; then
cat << 'EOF' > /var/www/sandbox/app/Http/Controllers/Controller.php
<?php
namespace App\Http\Controllers;
abstract class Controller { }
EOF
fi
"""
    await docker.copy_file(container, "/tmp/setup_sqlite.sh", sh_script)
    await docker.execute(container, "bash /tmp/setup_sqlite.sh", timeout=30, user="root")

async def place_code_in_laravel(container, info: ClassInfo) -> bool:
    """Inject code into the correct Laravel PSR-4 path and verify via Tinker."""
    dest_dir = shlex.quote(str(__import__('pathlib').Path(info.dest_file).parent))
    
    tinker_script = f"try {{ class_exists('{info.fqcn}') ? print('OK') : throw new Exception(); }} catch(Throwable $e) {{ print('ERR'); }}"
    b64_tinker = base64.b64encode(tinker_script.encode()).decode()
    
    cmd = (
        f"mkdir -p {dest_dir} && "
        f"cp /var/www/sandbox/submitted_code.php {shlex.quote(info.dest_file)} && "
        f"cd /var/www/sandbox && php artisan optimize:clear >/dev/null && "
        f"if [ ! -f /tmp/autoload_done ]; then composer dump-autoload -q && touch /tmp/autoload_done; fi && "
        f"php artisan tinker --execute=\"$(echo {b64_tinker} | base64 -d)\""
    )
    res = await docker.execute(container, cmd, timeout=settings.container_timeout_seconds)
    return "OK" in res.stdout and "ERR" not in res.stdout

async def scaffold_route(container, info: ClassInfo) -> None:
    """Idempotently register a resource route in api.php."""
    php_script = f"<?php $f='/var/www/sandbox/routes/api.php'; $c=file_get_contents($f); if(!str_contains($c,'{info.classname}::class')) file_put_contents($f,\"\\nRoute::apiResource('{info.route_resource}', \\\\{info.fqcn}::class);\\n\",FILE_APPEND);"
    await docker.copy_file(container, "/tmp/scaffold.php", php_script)
    await docker.execute(container, "php /tmp/scaffold.php && php /var/www/sandbox/artisan route:clear", timeout=10)

async def execute_code(container, code: str) -> dict:
    """Write and execute the provided PHP code in the sandbox using Tinker.
    
    NOTE: /var/www/sandbox/submitted_code.php is only written here for error detection *before*
    place_code_in_laravel has run.  Once the class is placed in its PSR-4 path
    (app/Http/Controllers/…) and autoloaded, we must NOT require() it again or
    PHP will fatal with "Cannot declare class X, already in use".  The guard
    below uses class_exists() with autoload=true to skip the require when the
    class is already available, which is the case on every iteration after the
    first patch is applied.
    """
    await docker.copy_code(container, code)
    
    # Detect the class name from the code so we can guard the require.
    # Falls back to requiring unconditionally when the class cannot be detected.
    tinker_code = (
        "try { "
        "$code = file_get_contents('/var/www/sandbox/submitted_code.php'); "
        "preg_match('/class\\s+(\\w+)/', $code, $m); "
        "$cls = $m[1] ?? ''; "
        "if ($cls && class_exists($cls, true)) { "
        "  echo '[ALREADY_LOADED:' . $cls . ']'; "
        "} else { "
        "  require '/var/www/sandbox/submitted_code.php'; "
        "} "
        "} "
        "catch (Throwable $e) { echo $e->getMessage() . ' in ' . $e->getFile() . ':' . $e->getLine() . \"\\n\" . $e->getTraceAsString(); exit(1); }"
    )
    b64_code = base64.b64encode(tinker_code.encode()).decode()
    
    res = await docker.execute(
        container, 
        f"cd /var/www/sandbox && php artisan tinker --execute=\"$(echo {b64_code} | base64 -d)\"", 
        timeout=15
    )
    
    return {
        "output": res.stdout,
        "error": res.stderr or res.stdout if res.exit_code != 0 else None,
        "exit_code": res.exit_code
    }
