<?php
namespace App\Http\Controllers;
class SlugController extends Controller {
    public function store() { return Str::slug('Example Post'); } // Missing use Str
}
