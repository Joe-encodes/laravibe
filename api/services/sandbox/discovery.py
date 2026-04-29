
import re
import logging
from api.services.sandbox import docker

logger = logging.getLogger(__name__)

async def discover_referenced_signatures(container, code: str) -> str:
    """
    Finds referenced classes in the code (via 'use' statements) and
    extracts their method signatures from the container.
    """
    # 1. Find 'use' statements (e.g. use App\Models\User;)
    refs = re.findall(r'^use\s+(App\\[^\s;]+);', code, re.MULTILINE)
    if not refs:
        return ""

    signatures = []
    for fqcn in set(refs):
        try:
            # 2. Extract signatures via reflection tinker snippet
            sig_cmd = (
                f'cd /var/www/sandbox && php artisan tinker --execute="'
                f'if (!class_exists(\'{fqcn}\')) exit(1); '
                f'$ref = new ReflectionClass(\'{fqcn}\'); '
                f'echo \"CLASS: {fqcn}\\n\"; '
                f'foreach ($ref->getMethods(ReflectionMethod::IS_PUBLIC) as $m) {{ '
                f'  if ($m->getDeclaringClass()->getName() !== \'{fqcn}\') continue; '
                f'  $params = collect($m->getParameters())->map(fn($p) => ($p->hasType() ? $p->getType() . \" \" : \"\") . \"$\" . $p->getName())->join(\", \"); '
                f'  echo \"  function \". $m->getName() .\"(\". $params .\")\" . ($m->hasReturnType() ? \": \" . $m->getReturnType() : \"\") . \"\\n\"; '
                f'}}"'
            )
            res = await docker.execute(container, sig_cmd, timeout=10)
            if res.exit_code == 0:
                signatures.append(res.stdout.strip())
        except Exception as e:
            logger.warning(f"Failed to discover signature for {fqcn}: {e}")

    return "\n\n".join(signatures) if signatures else ""
