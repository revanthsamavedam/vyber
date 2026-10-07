"""Auth seam tests.

The JWT tests use a real RSA key and a real local JWKS HTTP server —
the same shape as pointing VYBER_JWT_JWKS_URL at an identity provider
or an internal JWT authorization service. Tokens are minted locally;
nothing external is contacted.
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# The sandbox may route HTTP through a proxy; loopback must go direct.
os.environ["no_proxy"] = (os.environ.get("no_proxy", "") +
                          ",127.0.0.1,localhost").strip(",")

import jwt as pyjwt  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from api.auth import (AuthError, DemoAuthenticator, JWTAuthenticator,  # noqa: E402
                      build_authenticator)

ISSUER = "https://issuer.example"
AUDIENCE = "vyber-api"
KID = "test-key-1"


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key()


PRIVATE_KEY, PUBLIC_KEY = _keypair()
OTHER_PRIVATE_KEY, _ = _keypair()


def _jwks_json() -> str:
    jwk = pyjwt.algorithms.RSAAlgorithm.to_jwk(PUBLIC_KEY, as_dict=True)
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return json.dumps({"keys": [jwk]})


@pytest.fixture(scope="module")
def jwks_url():
    body = _jwks_json().encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/jwks.json"
    server.shutdown()


def _token(private_key=PRIVATE_KEY, claim="upn", caller="alice@example.com",
           audience=AUDIENCE, issuer=ISSUER, expires_delta=3600) -> str:
    now = int(time.time())
    payload = {"iss": issuer, "aud": audience, "iat": now,
               "exp": now + expires_delta, claim: caller}
    return pyjwt.encode(payload, private_key, algorithm="RS256",
                        headers={"kid": KID})


def _authenticator(jwks_url, claim="upn") -> JWTAuthenticator:
    return JWTAuthenticator(jwks_url=jwks_url, issuer=ISSUER,
                            audience=AUDIENCE, user_claim=claim)


def test_jwt_valid_token_returns_configured_claim(jwks_url):
    auth = _authenticator(jwks_url)
    assert auth.authenticate("Bearer " + _token()) == "alice@example.com"


def test_jwt_wrong_audience_rejected(jwks_url):
    auth = _authenticator(jwks_url)
    with pytest.raises(AuthError):
        auth.authenticate("Bearer " + _token(audience="someone-else"))


def test_jwt_wrong_issuer_rejected(jwks_url):
    auth = _authenticator(jwks_url)
    with pytest.raises(AuthError):
        auth.authenticate("Bearer " + _token(issuer="https://evil.example"))


def test_jwt_expired_rejected(jwks_url):
    auth = _authenticator(jwks_url)
    with pytest.raises(AuthError):
        auth.authenticate("Bearer " + _token(expires_delta=-60))


def test_jwt_wrong_signing_key_rejected(jwks_url):
    auth = _authenticator(jwks_url)
    with pytest.raises(AuthError):
        auth.authenticate("Bearer " + _token(private_key=OTHER_PRIVATE_KEY))


def test_jwt_missing_and_demo_headers_rejected(jwks_url):
    auth = _authenticator(jwks_url)
    with pytest.raises(AuthError):
        auth.authenticate(None)
    with pytest.raises(AuthError):
        auth.authenticate("Bearer demo:alice")


def test_demo_authenticator_unchanged():
    auth = DemoAuthenticator()
    assert auth.authenticate("Bearer demo:alice") == "alice"
    with pytest.raises(AuthError):
        auth.authenticate("Bearer something-else")
    with pytest.raises(AuthError):
        auth.authenticate(None)


def test_build_authenticator_modes():
    assert build_authenticator({}).mode == "demo"
    with pytest.raises(RuntimeError):
        build_authenticator({"VYBER_AUTH_MODE": "jwt"})
    with pytest.raises(RuntimeError):
        build_authenticator({"VYBER_AUTH_MODE": "bogus"})


def test_curated_facts_reach_subagent_prompts(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import core.orchestrator as orch
    from core.schemas import Findings, RoutePlan, SubTask

    class FakeAgent:
        def __init__(self, output):
            self.output = output
            self.prompts = []

        async def run(self, prompt):
            self.prompts.append(prompt)
            return SimpleNamespace(output=self.output)

    plan = RoutePlan(tasks=[SubTask(id="r", agent="researcher", task="Find facts")])
    researcher = FakeAgent(Findings(summary="done"))
    monkeypatch.setattr(orch, "planner_agent", FakeAgent(plan))
    monkeypatch.setitem(orch.SUBAGENTS, "researcher", researcher)
    ctx = orch.Ctx(user_id="alice", workspace=tmp_path / "ws")
    ctx.memory.approve_fact("alice", "report_format", "one page, bullets",
                            approved_by="alice")
    asyncio.run(orch.ask("Research something", ctx))
    assert "one page, bullets" in researcher.prompts[0]
