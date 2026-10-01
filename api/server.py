"""Flask API for NEXORA AI Router."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from core.config import Settings, load_settings
from core.failover import AllProvidersFailedError, execute_with_failover
from core.registry import ProviderRegistry, build_registry
from core.request_analyzer import analyze
from core.router import NoProviderAvailableError, Router
from core.scoring_engine import ScoringEngine
from utils.logger import configure_logging, get_logger, log_event

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
TITLE_MAX_LENGTH = 40

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _error_response(status: int, code: str, message: str) -> tuple[Response, int]:
    return jsonify({"error": {"code": code, "message": message}}), status


def _json_object() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_request", "Request body must be a JSON object.")
    return body


def _required_text(body: dict, field: str, max_chars: int) -> str:
    value = body.get(field)
    if not isinstance(value, str):
        raise ApiError(400, "invalid_request", f"'{field}' must be a string.")
    value = value.strip()
    if not value:
        raise ApiError(400, "invalid_request", f"'{field}' must not be empty.")
    if len(value) > max_chars:
        raise ApiError(400, "input_too_large", f"'{field}' must be at most {max_chars} characters.")
    return value


def _failure_status(kinds: set[str]) -> tuple[int, str, str]:
    if kinds == {"rate_limited"}:
        return 429, "provider_rate_limited", "The AI provider rate limit was reached. Try again shortly."
    if kinds == {"auth"}:
        return 502, "provider_auth_error", "The AI provider rejected the server's credentials. Check the server configuration."
    if kinds == {"unavailable"}:
        return 503, "providers_unreachable", "No AI provider could be reached."
    return 502, "provider_error", "The AI provider failed to produce a response."


def create_app(
    settings: Settings | None = None,
    registry: ProviderRegistry | None = None,
    scoring: ScoringEngine | None = None,
) -> Flask:
    settings = settings or load_settings()
    configure_logging(settings.log_level)

    registry = registry or build_registry(settings)
    routing = settings.routing
    scoring = scoring or ScoringEngine(
        registry.names(),
        success_weight=routing.success_weight,
        latency_weight=routing.latency_weight,
        cooldown_failures=routing.cooldown_failures,
        cooldown_seconds=routing.cooldown_seconds,
    )
    router = Router(registry, scoring, routing)

    configured_names = {p for order in routing.task_preferences.values() for p in order}
    for provider in sorted(configured_names - set(registry.names())):
        log_event("config_unknown_provider", logging.WARNING, provider=provider)

    app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = settings.max_query_chars * 4 + 4096
    app.config["NEXORA_SETTINGS"] = settings

    log_event("startup", available=",".join(registry.available_names()) or "none")

    @app.after_request
    def add_security_headers(response: Response) -> Response:
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.path in ("/ask", "/generate-title", "/providers"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return _error_response(exc.status, exc.code, exc.message)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        codes = {
            400: "invalid_request", 404: "not_found", 405: "method_not_allowed",
            413: "request_too_large", 415: "unsupported_media_type",
        }
        status = exc.code or 500
        return _error_response(status, codes.get(status, "http_error"), exc.name)

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        get_logger().exception("unhandled_error")
        return _error_response(500, "internal_error", "An internal error occurred.")

    @app.get("/")
    def home():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/providers")
    def providers():
        return jsonify({"providers": registry.describe()})

    @app.post("/ask")
    def ask():
        started = time.perf_counter()
        body = _json_object()
        query = _required_text(body, "query", settings.max_query_chars)

        choice = body.get("ai_choice", "auto")
        if not isinstance(choice, str):
            raise ApiError(400, "invalid_request", "'ai_choice' must be a string.")
        choice = choice.strip().lower() or "auto"
        if choice != "auto" and not registry.is_known(choice):
            raise ApiError(400, "invalid_provider", "Unsupported 'ai_choice'. Use 'auto' or a listed provider.")

        use_failover = body.get("failover", True)
        if not isinstance(use_failover, bool):
            raise ApiError(400, "invalid_request", "'failover' must be a boolean.")

        task_type = analyze(query)
        log_event("request_received", query_chars=len(query), task=task_type, choice=choice)

        try:
            plan = router.plan(task_type, None if choice == "auto" else choice)
        except NoProviderAvailableError:
            if choice != "auto":
                raise ApiError(503, "provider_unavailable",
                               f"Provider '{choice}' is not configured on this server.") from None
            raise ApiError(503, "no_provider_available",
                           "No AI provider is configured. See the README for setup.") from None

        log_event("provider_selected", primary=plan[0], task=task_type, candidates=len(plan))

        try:
            result = execute_with_failover(
                plan, registry, scoring, query,
                max_attempts=routing.max_attempts if use_failover else 1,
            )
        except AllProvidersFailedError as exc:
            status, code, message = _failure_status(exc.error_kinds)
            raise ApiError(status, code, message) from None

        return jsonify({
            "response": result.text,
            "provider": result.provider,
            "task_type": task_type,
            "fallback_used": result.fallback_used,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        })

    @app.post("/generate-title")
    def generate_title():
        body = _json_object()
        text = _required_text(body, "text", settings.max_title_chars)
        collapsed = re.sub(r"\s+", " ", text)
        title = collapsed if len(collapsed) <= TITLE_MAX_LENGTH else collapsed[: TITLE_MAX_LENGTH - 1].rstrip() + "…"
        return jsonify({"title": title})

    return app
