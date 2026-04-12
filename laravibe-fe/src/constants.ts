export const INITIAL_PHP_CODE = `<?php

namespace App\\Http\\Controllers;

use App\\Models\\User;
use Illuminate\\Http\\Request;

class UserController extends Controller
{
    public function update(Request $request, $id)
    {
        // BUG: Missing validation
        // BUG: Insecure mass assignment
        $user = User::find($id);
        $user->update($request->all());
        
        return response()->json($user);
    }
}`;
