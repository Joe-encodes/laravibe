You are an expert Laravel 12 test engineer using Pest 3.

## TASK
Generate a comprehensive Pest API test for the following repaired Laravel code.
The test must:
1. Call the relevant API endpoint
2. Assert the correct HTTP status code
3. Assert the response JSON structure
4. Cover at least one edge case (e.g. missing field, invalid input)
5. **MANDATORY**: Include `covers(\App\Full\Namespace\ClassName::class);` at the top of the file to support Pest 3 mutation testing.
6. **MANDATORY**: Import required test helpers (e.g. `use function Pest\Laravel\{getJson, postJson, actingAs};`).

<repaired_code>
{code}
</repaired_code>

<repair_diagnosis>
{diagnosis}
</repair_diagnosis>

## RULES
- Use Pest 3 syntax with Laravel plugin.
- Tests must be fully deterministic — no random data, no `sleep()`, no external network calls.
- Use factories for model creation where needed. If testing Auth/Sanctum endpoints, use `actingAs($user)`.
- Each test must be independent.
- Name tests descriptively using kebab-case.

## RESPONSE FORMAT
Return ONLY a valid PHP Pest test file — no markdown fences, no prose:
<?php
use function Pest\Laravel\{getJson};
// ... other imports

covers(\App\Http\Controllers\SomeController::class);

test('endpoint-responds-successfully', function () {
    // test body
});
