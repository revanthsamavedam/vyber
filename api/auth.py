"""Authentication — the one seam where your identity system plugs in.

Everything downstream (session ownership, run ownership, traces) works
with a single string: the authenticated caller's id, stored on
`request.state.caller`. How that id is proven is isolated here, behind
`build_authenticator()`, selected by `VYBER_AUTH_MODE`:

  demo  (default)  `Authorization: Bearer demo:<user>` — local development
                   only. No cryptography, no secrets; never deploy it.

  jwt              `Authorization: Bearer <jwt>` validated against a JWKS
                   endpoint: signature (RS256/ES256), issuer, audience,
                   and expiry are all verified, failing closed. Point it
                   at your identity provider OR at your organization's
                   JWT authorization service — whichever signs the tokens
                   you forward. If the caller's id lives in a claim other
                   than `sub`, set VYBER_JWT_USER_CLAIM (e.g. `upn`,
                   `preferred_username`, `email`).

JWT configuration (all required in jwt mode; missing values are a
startup error, never a silent fall back to demo):

  VYBER_JWT_JWKS_URL    e.g. https://issuer.example/.well-known/jwks.json
  VYBER_JWT_ISSUER      expected `iss`
  VYBER_JWT_AUDIENCE    expected `aud`
  VYBER_JWT_USER_CLAIM  optional, default `sub`
  VYBER_JWT_ALGORITHMS  optional, default `RS256,ES256`

Note: PyJWKClient caches signing keys, so the JWKS fetch happens on the
first request per key id, not per request.
"""
from __future__ import annotations

import os
import re

CALLER_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,128}$")


class AuthError(Exception):
    """The request carries no acceptable credential."""


class DemoAuthenticator:
    mode = "demo"

    def authenticate(self, authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer demo:"):
            raise AuthError("sign-in required")
        caller = authorization.removeprefix("Bearer demo:").split(":")[0]
        if not CALLER_RE.match(caller):
            raise AuthError("sign-in required")
        return caller


class JWTAuthenticator:
    mode = "jwt"

    def __init__(self, jwks_url: str, issuer: str, audience: str,
                 user_claim: str = "sub",
                 algorithms: tuple[str, ...] = ("RS256", "ES256")):
        import jwt  # PyJWT — imported lazily so demo mode stays light
        self._jwt = jwt
        self._client = jwt.PyJWKClient(jwks_url, cache_keys=True)
        self._issuer = issuer
        self._audience = audience
        self._user_claim = user_claim
        self._algorithms = algorithms

    def authenticate(self, authorization: str | None) -> str:
        jwt = self._jwt
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthError("sign-in required")
        token = authorization.removeprefix("Bearer ").strip()
        if not token or token.startswith("demo:"):
            raise AuthError("sign-in required")
        try:
            signing_key = self._client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token, signing_key.key,
                algorithms=list(self._algorithms),
                issuer=self._issuer, audience=self._audience,
                options={"require": ["exp", "iss", "aud"]})
        except jwt.PyJWTError as e:
            raise AuthError("invalid token") from e
        caller = payload.get(self._user_claim)
        if isinstance(caller, list):
            caller = caller[0] if caller else None
        if caller is None or not CALLER_RE.match(str(caller)):
            raise AuthError("token carries no usable caller identity")
        return str(caller)


def build_authenticator(env: dict | None = None):
    env = os.environ if env is None else env
    mode = (env.get("VYBER_AUTH_MODE") or "demo").strip().lower()
    if mode == "demo":
        return DemoAuthenticator()
    if mode == "jwt":
        missing = [name for name in
                   ("VYBER_JWT_JWKS_URL", "VYBER_JWT_ISSUER", "VYBER_JWT_AUDIENCE")
                   if not env.get(name)]
        if missing:
            raise RuntimeError(
                "VYBER_AUTH_MODE=jwt requires: " + ", ".join(missing))
        algorithms = tuple(
            a.strip() for a in
            (env.get("VYBER_JWT_ALGORITHMS") or "RS256,ES256").split(",")
            if a.strip())
        return JWTAuthenticator(
            jwks_url=env["VYBER_JWT_JWKS_URL"],
            issuer=env["VYBER_JWT_ISSUER"],
            audience=env["VYBER_JWT_AUDIENCE"],
            user_claim=env.get("VYBER_JWT_USER_CLAIM") or "sub",
            algorithms=algorithms)
    raise RuntimeError(f"unknown VYBER_AUTH_MODE: {mode!r} (use demo or jwt)")
