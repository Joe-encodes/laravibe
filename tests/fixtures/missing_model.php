<?php
// tests/fixtures/missing_model.php
// Bug: References App\Models\Product which does not exist in a fresh Laravel install
// Expected: AI creates the missing model (or redirects to existing equivalent)

use App\Http\Controllers\Controller;
use App\Models\Product;
use Illuminate\Http\JsonResponse;

class ProductController extends Controller
{
    public function index(): JsonResponse
    {
        $products = Product::all();

        return response()->json([
            'data' => $products,
            'count' => $products->count(),
        ]);
    }

    public function show(int $id): JsonResponse
    {
        $product = Product::findOrFail($id);

        return response()->json(['data' => $product]);
    }
}
