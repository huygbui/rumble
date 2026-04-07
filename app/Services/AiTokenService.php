<?php

namespace App\Services;

use App\Models\User;
use Firebase\JWT\JWT;

class AiTokenService
{
    /**
     * Mint a short-lived HS256 JWT that the Python AI server can self-validate
     * with the shared secret. Carries only the minimum claims needed to identify
     * the user — no PII, no Passport token, no DB lookup required server-side.
     */
    public function mint(User $user): array
    {
        $now = time();
        $ttl = (int) config('services.ai_jwt.ttl', 300);

        $payload = [
            'iss' => config('services.ai_jwt.issuer'),
            'aud' => config('services.ai_jwt.audience'),
            'sub' => (string) $user->getKey(),
            'iat' => $now,
            'exp' => $now + $ttl,
        ];

        $token = JWT::encode(
            $payload,
            config('services.ai_jwt.secret'),
            'HS256'
        );

        return [
            'ai_token' => $token,
            'expires_in' => $ttl,
            'expires_at' => $now + $ttl,
        ];
    }
}
