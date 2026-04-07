<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Services\AiTokenService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class AiTokenController extends Controller
{
    public function __construct(private AiTokenService $aiTokens) {}

    /**
     * Mint a 5-minute JWT the browser uses to open a WebSocket to the
     * Python AI server. The Python server validates this token entirely
     * offline using the shared HS256 secret.
     */
    public function __invoke(Request $request): JsonResponse
    {
        return response()->json(
            $this->aiTokens->mint($request->user())
        );
    }
}
