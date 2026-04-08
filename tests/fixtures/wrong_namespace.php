<?php
// tests/fixtures/wrong_namespace.php
// Bug: Declares namespace App\Http\Controllers\Api\V1 but is treated as a root controller
// This causes "Class not found" when Laravel's autoloader looks in the wrong directory

namespace App\Http\Controllers\Api\V1;  // <-- wrong: file lives at root level

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class UserController
{
    public function index(): JsonResponse
    {
        return response()->json([
            'data' => \App\Models\User::paginate(15),
        ]);
    }

    public function store(Request $request): JsonResponse
    {
        $request->validate([
            'name'  => 'required|string|max:255',
            'email' => 'required|email|unique:users',
        ]);

        $user = \App\Models\User::create($request->only('name', 'email'));

        return response()->json(['data' => $user], 201);
    }
}
