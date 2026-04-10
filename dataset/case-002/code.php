<?php

namespace App\Controllers;

use Illuminate\Http\JsonResponse;

class OrderController extends \App\Http\Controllers\Controller
{
    public function index(): JsonResponse
    {
        return response()->json([
            'status' => 'ok',
            'orders' => [],
        ]);
    }
}
