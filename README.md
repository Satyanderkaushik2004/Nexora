# NEXORA AI Router

NEXORA is a small multi-provider AI routing layer. It classifies each request, picks the most suitable
configured provider (OpenAI, DeepSeek, Perplexity, or a local Ollama model), and automatically fails over
to another provider if the first one fails. It ships with a Flask API and a lightweight web interface.

## Features

- **Multi-provider routing** across OpenAI, DeepSeek, Perplexity, and local Ollama models
- **Automatic task classification** (`coding`, `research`, `general`) using keyword matching
- **Manual provider selection** from the UI or the API (`ai_choice`)
- **Provider failover** with a configurable attempt limit
- **Performance-aware scoring**: observed success rate and latency influence provider ranking, and
  repeatedly failing providers are temporarily skipped
- **Graceful degradation**: a provider without credentials is marked unavailable and never selected;
  the rest of the application keeps working
- **Local-first option**: Ollama needs no API key
- **Credentials from the environment only** — nothing is hardcoded
- **Web interface** with chat history (in memory), provider selector, side-by-side compare mode,
  latency/provider badges, and optional browser voice input

## Architecture

```text
Frontend (static HTML/JS)
        ↓
Flask API  (validation, error mapping)
        ↓
Request Analyzer  →  task type
        ↓
Router  (task preference + performance score, available providers only)
        ↓
Provider Registry  (OpenAI · DeepSeek · Perplexity · Local/Ollama)
        ↓
Failover  (primary → next-ranked providers → safe error)
        ↓
Response  (text + which provider answered)
```

### How routing works

For every *configured* provider the router computes

```text
final = preference_weight × preference_score(task, provider)
      + performance_weight × performance_score(provider)
```

- **Preference** comes from the ordered per-task lists in `configs/config.json`
  (for example `coding: deepseek → openai → local → perplexity`).
- **Performance** comes from the scoring engine: a smoothed success rate blended with average latency.
  A provider that has never been called gets a neutral score. After several consecutive failures a
  provider is skipped for a cooldown period (unless nothing else is available).
- If you pick a provider manually, it becomes the primary and the automatically ranked providers
  follow as fallbacks.

Scores are held in memory and reset when the server restarts.

## Installation

```bash
git clone <repository-url>
cd nexora-ai-router

python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

Developed and tested on Python 3.12 (3.10+ is expected to work).

## Configuration

Copy the example file and fill in only the providers you want:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | _(empty)_ | Enables the OpenAI provider |
| `DEEPSEEK_API_KEY` | _(empty)_ | Enables the DeepSeek provider |
| `PERPLEXITY_API_KEY` | _(empty)_ | Enables the Perplexity provider |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model name |
| `DEEPSEEK_MODEL` | `deepseek-chat` | DeepSeek model name |
| `PERPLEXITY_MODEL` | `sonar` | Perplexity model name |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3` | Ollama model name |
| `OLLAMA_TIMEOUT` | `120` | Seconds to wait for the local model |
| `NEXORA_REQUEST_TIMEOUT` | `60` | Seconds to wait for cloud providers |
| `NEXORA_HOST` | `127.0.0.1` | Bind address |
| `NEXORA_PORT` | `5000` | Port |
| `NEXORA_DEBUG` | `false` | Flask debug mode (development only; refused unless the host is `127.0.0.1`) |
| `NEXORA_LOG_LEVEL` | `INFO` | Log level |
| `NEXORA_MAX_QUERY_CHARS` | `8000` | Maximum accepted query length |
| `NEXORA_CONFIG` | `configs/config.json` | Alternate routing config file |

Routing behaviour lives in `configs/config.json`:

```json
{
  "routing": {
    "task_preferences": {
      "coding":   ["deepseek", "openai", "local", "perplexity"],
      "research": ["perplexity", "openai", "deepseek", "local"],
      "general":  ["local", "openai", "deepseek", "perplexity"]
    },
    "preference_weight": 0.6,
    "performance_weight": 0.4
  },
  "scoring": {
    "success_weight": 0.7,
    "latency_weight": 0.3,
    "cooldown_after_consecutive_failures": 3,
    "cooldown_seconds": 60
  },
  "failover": { "max_attempts": 3 }
}
```

Provider names are `openai`, `deepseek`, `perplexity`, and `local`. Invalid configuration stops the
server at startup with a clear message.

### Using Ollama

Install [Ollama](https://ollama.com), pull a model (`ollama pull llama3`), and make sure it is running.
No key is needed. If Ollama is not running, the local provider simply fails and routing falls back to
other providers.

## Running

```bash
python main.py
```

Then open <http://127.0.0.1:5000>.

`python main.py` starts Flask's development server, which is fine for local use. For a shared or
production deployment run the app behind a production WSGI server, for example:

```bash
pip install gunicorn
gunicorn -b 127.0.0.1:5000 "api.server:create_app()"
```

Note that provider scores are kept per process, so each worker keeps its own statistics.

## API

All endpoints exchange JSON. Errors always have the shape
`{"error": {"code": "...", "message": "..."}}`.

### `POST /ask`

| Field | Type | Required | Description |
|---|---|---|---|
| `query` | string | yes | The prompt (non-empty, up to `NEXORA_MAX_QUERY_CHARS`) |
| `ai_choice` | string | no | `auto` (default), `openai`, `deepseek`, `perplexity`, or `local` |
| `failover` | boolean | no | Set `false` to disable fallback to other providers (default `true`) |

```bash
curl -X POST http://127.0.0.1:5000/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "Write a Python function that reverses a string", "ai_choice": "auto"}'
```

```json
{
  "response": "Here is a function...",
  "provider": "deepseek",
  "task_type": "coding",
  "fallback_used": false,
  "latency_ms": 1420
}
```

`provider` is always the provider that actually produced the answer, and `fallback_used` tells you
whether failover happened.

| Status | `error.code` | Meaning |
|---|---|---|
| 400 | `invalid_request`, `input_too_large`, `invalid_provider` | Malformed JSON, wrong types, empty/oversized input, unknown `ai_choice` |
| 413 | `request_too_large` | Request body too large |
| 429 | `provider_rate_limited` | Every attempted provider reported a rate limit |
| 502 | `provider_error`, `provider_auth_error` | Upstream failure, or the provider rejected the server's configured credentials |
| 503 | `no_provider_available`, `provider_unavailable`, `providers_unreachable` | Nothing configured, the chosen provider is not configured, or no provider could be reached |
| 500 | `internal_error` | Unexpected server error (details are only in the server log) |

The API itself has no inbound authentication, so 401/403 are not used; see [Security](#security).

### `POST /generate-title`

Returns a short chat title (the first 40 characters of the text, whitespace-collapsed).
It does not call an AI provider.

```bash
curl -X POST http://127.0.0.1:5000/generate-title \
  -H "Content-Type: application/json" \
  -d '{"text": "How do I reverse a linked list in Python?"}'
```

```json
{ "title": "How do I reverse a linked list in Pytho…" }
```

### `GET /providers`

Lists providers and whether each is available (configured). Contains no secrets.

```json
{
  "providers": [
    { "name": "openai", "display_name": "OpenAI", "model": "gpt-4o-mini", "available": false },
    { "name": "local", "display_name": "Local (Ollama)", "model": "llama3", "available": true }
  ]
}
```

## Web interface

Served at `/`. It loads its own bundled assets (no CDN requests) and renders model output as Markdown
sanitized with DOMPurify. Chats live in the browser tab's memory and are lost on reload. The microphone
button appears only in browsers that support the Web Speech API; in some browsers that feature sends
audio to the browser vendor's speech service.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

The tests use mock providers and require no API keys or network access.

## Security

- Credentials are read from environment variables (optionally from a local `.env`). `.env` is
  git-ignored and no credentials are committed. Use `.env.example` as the template.
- Provider errors are sanitized: upstream response bodies, headers, and exception text are never
  returned to clients or written to logs.
- Logs record metadata only (task type, provider, latency, prompt *length*) — never prompt text,
  keys, or authorization headers. A redaction filter also masks key-shaped strings as a safety net.
- Input is validated (JSON object, string types, length limits, known providers) and request size is capped.
- Flask debug mode is off by default and refused on non-loopback hosts. The server binds to
  `127.0.0.1` by default.
- No CORS headers are sent; the UI is served from the same origin. Responses carry a restrictive
  Content-Security-Policy and other basic security headers.
- If you ever committed a real key to a repository, revoke and rotate it; removing it from the
  latest commit does not remove it from Git history.

## Limitations

- **No inbound authentication or rate limiting.** Anyone who can reach the server can spend your
  provider credits. Keep it on localhost, or put it behind an authenticating reverse proxy.
- Task classification is simple keyword matching and will misclassify some requests.
- Provider scores and chat history are in memory only (per process / per browser tab).
- Each request is stateless: there is no multi-turn conversation context sent to providers.
- Responses are returned whole; there is no streaming.
- `/generate-title` truncates text rather than generating a title with a model.
- Only text chat is supported; there is no file upload.
- The Flask development server is not meant for production traffic.

## Future improvements

- Optional API-key authentication and per-client rate limiting
- Multi-turn conversation context
- Streaming responses
- Persistent chat history and statistics
- Additional providers via the registry

## Project structure

```text
nexora-ai-router/
├── api/server.py            Flask app factory, validation, error handling
├── clients/                 Provider clients (OpenAI, DeepSeek, Perplexity, Ollama)
├── configs/config.json      Routing, scoring, and failover settings
├── core/
│   ├── config.py            Environment + config loading
│   ├── registry.py          Provider registry
│   ├── request_analyzer.py  Task classification
│   ├── router.py            Provider selection
│   ├── scoring_engine.py    Success/latency scoring and cooldowns
│   └── failover.py          Ordered failover execution
├── frontend/                Web UI (index.html, app.js, styles.css, vendor/)
├── tests/                   pytest suite
├── utils/logger.py          Credential-safe logging
├── .env.example
├── main.py
└── requirements.txt
```
