<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\Product;
use Illuminate\Http\JsonResponse;

class ProductController extends Controller
{
    public function index(): JsonResponse
    {
        return response()->json([
            'data' => Product::all(),
        ]);
    }

    public function show(int $id): JsonResponse
    {
        $product = Product::findOrFail($id);
        return response()->json(['data' => $product]);
    }
}
