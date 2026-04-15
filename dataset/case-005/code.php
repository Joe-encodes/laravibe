<?php
// dataset/case-005/code.php
// Bug: Function signature says JsonResponse, but returns a string.
// Expected: AI wraps result in response()->json()

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use Illuminate\Http\JsonResponse;

class StatusController extends Controller
{
    public function check(): JsonResponse
    {
        // Bug: Typed return expects JsonResponse, but returning string
        // Will throw: Return value must be of type JsonResponse, string returned
        return "Service is operational";
    }

    public function ok(): JsonResponse
    {
        return response()->json(['status' => 'ok']);
    }
}
