<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use Illuminate\Http\JsonResponse;

class SlugController extends Controller
{
    public function generate(string $title): JsonResponse
    {
        $slug = Str::slug($title);
        $uuid = Str::uuid();

        return response()->json([
            'slug' => $slug,
            'uuid' => $uuid,
        ]);
    }
}
