<?php
// dataset/case-004/code.php
// Bug: Calling 'nonExistentMethod' on a Collection
// Expected: AI replaces it with 'map' or 'each' or similar

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Collection;

class StatsController extends Controller
{
    public function index(): JsonResponse
    {
        $data = collect([1, 2, 3, 4, 5]);

        // Bug: 'calculateAverage' is not a method on Collection
        // Correct method would be 'avg()' or 'average()'
        $average = $data->calculateAverage();

        return response()->json([
            'average' => $average,
            'count' => $data->count(),
        ]);
    }
}
