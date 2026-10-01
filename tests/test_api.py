import pytest

from clients.base import ProviderError, ProviderRateLimitError, ProviderUnavailableError
from tests.conftest import FakeClient

SECRET = "sk-test-not-a-real-key-123456"


def raiser(exc):
    def _raise(_):
        raise exc
    return _raise


@pytest.fixture
def client(make_app, four_clients):
    app, _ = make_app(four_clients)
    return app.test_client()


def error_code(resp):
    return resp.get_json()["error"]["code"]


# ---------- validation ----------
@pytest.mark.parametrize("payload,code", [
    ({}, "invalid_request"),
    ({"query": ""}, "invalid_request"),
    ({"query": "   "}, "invalid_request"),
    ({"query": 123}, "invalid_request"),
    ({"query": ["x"]}, "invalid_request"),
    ({"query": "hi", "ai_choice": 5}, "invalid_request"),
    ({"query": "hi", "ai_choice": "gemini"}, "invalid_provider"),
    ({"query": "hi", "failover": "yes"}, "invalid_request"),
    ({"query": "x" * 9000}, "input_too_large"),
])
def test_ask_rejects_bad_input(client, payload, code):
    resp = client.post("/ask", json=payload)
    assert resp.status_code == 400 and error_code(resp) == code


def test_ask_rejects_non_json_and_non_object(client):
    assert client.post("/ask", data="hello", content_type="text/plain").status_code == 400
    assert client.post("/ask", data="{bad", content_type="application/json").status_code == 400
    assert client.post("/ask", json=["a", "list"]).status_code == 400
    assert client.post("/ask").status_code == 400


def test_oversized_body_is_rejected(client):
    resp = client.post("/ask", data="x" * 200_000, content_type="application/json")
    assert resp.status_code == 413 and error_code(resp) == "request_too_large"


# ---------- routing ----------
def test_auto_routing_by_task(client):
    assert client.post("/ask", json={"query": "write a python function"}).get_json()["provider"] == "deepseek"
    assert client.post("/ask", json={"query": "latest news on space"}).get_json()["provider"] == "perplexity"
    data = client.post("/ask", json={"query": "tell me a joke"}).get_json()
    assert data["provider"] == "local" and data["task_type"] == "general"
    assert data["fallback_used"] is False and data["response"] == "local says hi"


def test_manual_choice_is_honoured(client):
    data = client.post("/ask", json={"query": "write code", "ai_choice": "OpenAI "}).get_json()
    assert data["provider"] == "openai"


def test_manual_choice_unconfigured_gives_clear_error(make_app):
    app, _ = make_app([FakeClient("openai", configured=False), FakeClient("local")])
    resp = app.test_client().post("/ask", json={"query": "hi", "ai_choice": "openai"})
    assert resp.status_code == 503 and error_code(resp) == "provider_unavailable"
    assert "openai" in resp.get_json()["error"]["message"]


def test_no_provider_configured(make_app):
    app, _ = make_app([FakeClient("openai", configured=False)])
    resp = app.test_client().post("/ask", json={"query": "hi"})
    assert resp.status_code == 503 and error_code(resp) == "no_provider_available"


def test_unconfigured_provider_skipped_in_auto_mode(make_app):
    clients = [FakeClient("deepseek", configured=False), FakeClient("openai"), FakeClient("local")]
    app, _ = make_app(clients)
    data = app.test_client().post("/ask", json={"query": "write code"}).get_json()
    assert data["provider"] == "openai"


# ---------- failover through the API ----------
def test_failover_reports_fallback(make_app):
    clients = [FakeClient("deepseek", behavior=raiser(ProviderUnavailableError("x"))), FakeClient("openai")]
    app, _ = make_app(clients)
    resp = app.test_client().post("/ask", json={"query": "write code"})
    data = resp.get_json()
    assert resp.status_code == 200 and data["provider"] == "openai" and data["fallback_used"] is True


def test_failover_can_be_disabled(make_app):
    clients = [FakeClient("deepseek", behavior=raiser(ProviderUnavailableError())), FakeClient("openai")]
    app, registry = make_app(clients)
    resp = app.test_client().post("/ask", json={"query": "hi", "ai_choice": "deepseek", "failover": False})
    assert resp.status_code == 503
    assert registry.get("openai").calls == 0


def test_all_rate_limited_returns_429(make_app):
    clients = [FakeClient("a", behavior=raiser(ProviderRateLimitError())),
               FakeClient("b", behavior=raiser(ProviderRateLimitError()))]
    app, _ = make_app(clients)
    assert app.test_client().post("/ask", json={"query": "hi"}).status_code == 429


def test_all_unreachable_returns_503(make_app):
    clients = [FakeClient("a", behavior=raiser(ProviderUnavailableError()))]
    app, _ = make_app(clients)
    assert app.test_client().post("/ask", json={"query": "hi"}).status_code == 503


def test_mixed_upstream_failures_return_502(make_app):
    clients = [FakeClient("a", behavior=raiser(RuntimeError("boom"))),
               FakeClient("b", behavior=raiser(ProviderError("x", 500)))]
    app, _ = make_app(clients)
    resp = app.test_client().post("/ask", json={"query": "hi"})
    assert resp.status_code == 502


def test_errors_never_leak_internals(make_app):
    leak = f"Bearer {SECRET} at /home/user/app/clients/x.py"
    clients = [FakeClient("a", behavior=raiser(RuntimeError(leak)))]
    app, _ = make_app(clients)
    resp = app.test_client().post("/ask", json={"query": "hi"})
    body = resp.get_data(as_text=True)
    assert SECRET not in body and "/home/user" not in body and "Traceback" not in body


def test_unhandled_error_is_generic_500(make_app, monkeypatch):
    app, _ = make_app([FakeClient("a")])
    import api.server as server
    monkeypatch.setattr(server, "analyze", raiser(RuntimeError(f"secret {SECRET}")))
    resp = app.test_client().post("/ask", json={"query": "hi"})
    assert resp.status_code == 500 and error_code(resp) == "internal_error"
    assert SECRET not in resp.get_data(as_text=True)


def test_prompt_text_is_not_logged(make_app, caplog):
    import logging
    logging.getLogger("nexora").propagate = True
    app, _ = make_app([FakeClient("local")])
    with caplog.at_level(logging.DEBUG, logger="nexora"):
        app.test_client().post("/ask", json={"query": "my private diary entry about Zebra"})
    assert "Zebra" not in caplog.text and "private diary" not in caplog.text
    assert "query_chars=" in caplog.text


# ---------- other endpoints ----------
def test_generate_title(client):
    assert client.post("/generate-title", json={"text": "Hello   world"}).get_json() == {"title": "Hello world"}
    long = client.post("/generate-title", json={"text": "word " * 40}).get_json()["title"]
    assert len(long) <= 40 and long.endswith("…")


@pytest.mark.parametrize("payload", [{}, {"text": ""}, {"text": 5}, {"text": "x" * 5000}])
def test_generate_title_validation(client, payload):
    assert client.post("/generate-title", json=payload).status_code == 400


def test_providers_endpoint_exposes_no_secrets(client):
    data = client.get("/providers").get_json()["providers"]
    assert {p["name"] for p in data} == {"openai", "deepseek", "perplexity", "local"}
    assert all(set(p) == {"name", "display_name", "model", "available"} for p in data)


def test_home_and_static_assets(client):
    page = client.get("/")
    assert page.status_code == 200 and b"NEXORA" in page.data
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/../main.py").status_code == 404


def test_security_headers_and_json_404(client):
    resp = client.get("/nope")
    assert resp.status_code == 404 and error_code(resp) == "not_found"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in resp.headers["Content-Security-Policy"]
    assert client.get("/ask").status_code == 405


def test_no_cors_headers(client):
    resp = client.post("/ask", json={"query": "hi"}, headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in resp.headers
