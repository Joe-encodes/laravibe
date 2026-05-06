<?php

namespace App\Http\Controllers;

use App\Models\Comment;
use App\Models\Post;
use App\Models\Video;
use Illuminate\Http\Request;

class PolymorphicController extends Controller
{
    /**
     * Store a comment for a post or video.
     * This is intentionally broken:
     * 1. Models don't have polymorphic relations defined.
     * 2. Migration for comments is missing morph columns.
     */
    public function store(Request $request)
    {
        $request->validate([
            'body' => 'required|string',
            'commentable_id' => 'required|integer',
            'commentable_type' => 'required|string|in:post,video',
        ]);

        $type = $request->input('commentable_type');
        $id = $request->input('commentable_id');

        $commentable = ($type === 'post') 
            ? Post::findOrFail($id) 
            : Video::findOrFail($id);

        // This will fail because the 'comments' relation is not defined on Post/Video
        // and even if it was, the DB doesn't have the columns yet.
        $comment = $commentable->comments()->create([
            'body' => $request->input('body'),
        ]);

        return response()->json($comment, 201);
    }
}
