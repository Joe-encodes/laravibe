<?php

namespace App\Http\Controllers;

use App\Services\ServiceA;
use Illuminate\Http\Request;

class CircularController extends Controller
{
    protected $serviceA;

    public function __construct(ServiceA $serviceA)
    {
        $this->serviceA = $serviceA;
    }

    public function index()
    {
        return response()->json([
            'message' => $this->serviceA->doSomething(),
        ]);
    }
}

namespace App\Services;

class ServiceA
{
    protected $serviceB;

    public function __construct(ServiceB $serviceB)
    {
        $this->serviceB = $serviceB;
    }

    public function doSomething()
    {
        return $this->serviceB->doOther();
    }
}

class ServiceB
{
    protected $serviceA;

    public function __construct(ServiceA $serviceA)
    {
        $this->serviceA = $serviceA;
    }

    public function doOther()
    {
        return "Circular!";
    }
}
