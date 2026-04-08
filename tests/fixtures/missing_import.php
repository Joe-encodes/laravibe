<?php
// tests/fixtures/missing_import.php
// Bug: Uses Str:: and Arr:: facades without importing them
// PHP will throw: Error: Class "Str" not found

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class UtilController
{
    public function slugify(Request $request): JsonResponse
    {
        $request->validate(['text' => 'required|string']);

        // BUG: Str is used but not imported
        $slug = Str::slug($request->input('text'));

        // BUG: Arr is used but not imported
        $words = Arr::wrap(explode('-', $slug));

        return response()->json([
            'slug'  => $slug,
            'words' => $words,
            'count' => count($words),
        ]);
    }
}
