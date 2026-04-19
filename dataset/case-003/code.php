<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class ContentController extends Controller
{
    /**
     * Generate a URL-safe slug from an article title.
     */
    public function generateSlug(Request $request): JsonResponse
    {
        $request->validate(['title' => 'required|string|max:255']);

        $slug = Str::slug($request->input('title'));
        return response()->json(['slug' => $slug]);
    }

    /**
     * Return a formatted content summary from an array of tags.
     */
    public function summarize(Request $request): JsonResponse
    {
        $request->validate(['tags' => 'required|array']);

        $tags    = $request->input('tags');
        $unique  = Arr::flatten(array_unique($tags));
        $preview = Arr::first($unique, fn($tag) => strlen($tag) > 3);

        return response()->json([
            'tag_count'   => count($unique),
            'preview_tag' => $preview,
        ]);
    }

    /**
     * Return publishing metadata for a given content item.
     */
    public function publishedAt(Request $request): JsonResponse
    {
        $request->validate(['timestamp' => 'required|integer']);

        $date = Carbon::createFromTimestamp($request->integer('timestamp'));

        return response()->json([
            'human_readable' => $date->diffForHumans(),
            'iso'            => $date->toIso8601String(),
        ]);
    }
}
