<?php
namespace App\Http\Api; // Should be App\Http\Controllers
class UserController extends Controller {
    public function index() { return response()->json(['ok']); }
}
