<?php

namespace App\Http\Controllers;

use App\Contracts\PaymentGateway;
use Illuminate\Http\Request;

class PaymentController extends Controller
{
    protected $gateway;

    public function __construct(PaymentGateway $gateway)
    {
        $this->gateway = $gateway;
    }

    public function pay(Request $request)
    {
        return response()->json([
            'status' => $this->gateway->charge($request->amount),
        ]);
    }
}

namespace App\Providers;

use Illuminate\Support\ServiceProvider;
use App\Contracts\PaymentGateway;
use App\Services\StripeGateway; // This class does NOT exist

class PaymentServiceProvider extends ServiceProvider
{
    public function register()
    {
        $this->app->singleton(PaymentGateway::class, function ($app) {
            return new StripeGateway();
        });
    }
}
