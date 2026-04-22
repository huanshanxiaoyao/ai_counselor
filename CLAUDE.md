# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Counselor is a Django + Channels application with two features:
1. **Chat** (`/`): Side-by-side comparison of responses from multiple LLM providers
2. **Roundtable** (`/roundtable/`): Real-time AI discussion room where historical-figure AI characters debate a topic via WebSocket

## Commands

### Development server
```bash
# From project root (ASGI required for WebSocket support)
cd backend && daphne -p 8000 backend.config.asgi:application

# Or standard Django (no WebSocket)
cd backend && python manage.py runserver
```

### Database migrations
```bash
cd backend && python manage.py migrate
```

### Tests
```bash
# Run all tests (from project root)
pytest tests/

# Run a single test file
pytest tests/test_api.py -v

# Run a single test
pytest tests/test_api.py::TestClassName::test_method_name -v

# The CI also runs: pytest backend/ -v
```

### Lint & type check
```bash
ruff check backend llm
mypy backend llm --ignore-missing-imports
```

### Django system check (uses test settings, no real DB needed)
```bash
cd backend && python manage.py check --settings=config.settings_test
```

## Environment Setup

Copy `.env.example` to `.env` and fill in API keys. Required for LLM calls:
- `QWEN_API_KEY`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY` (used for MiniMax), `DOUBAO_API_KEY`
- `LLM_DEFAULT_PROVIDER` defaults to `qwen`

For production (`DEBUG=0`), `DJANGO_SECRET_KEY` and `ALLOWED_HOSTS` are also required — see `.env.example`.

Redis is optional — the app auto-detects it and falls back to `InMemoryChannelLayer` (single-process only).

### Authentication

Anonymous access is enabled by default. Authentication is required only for specific actions (for example, creating private discussions). Login and signup pages are available at `/accounts/login/` and `/accounts/signup/`.

If you need an admin account after `migrate`, create one with:

```bash
cd backend && python manage.py createsuperuser
```

For guarded API actions, unauthenticated requests return `401 JSON` with a `login_url` hint.

## Architecture

### Backend structure
```
backend/
  config/          # Django settings, root URLs, ASGI/WSGI
  chat/            # Multi-provider chat comparison (HTTP only)
  roundtable/      # AI discussion room (HTTP + WebSocket)
  llm/             # Unified LLM client abstraction
    client.py      # LLMClient, OpenAIBackend, AnthropicBackend
    providers.py   # ProviderConfig, env-based provider registry
    exceptions.py  # Typed LLM exceptions
```

Templates live at the project root (`templates/`), not inside apps. Static files are at `static/`. There is no frontend build step — all UI is Django server-rendered templates with vanilla JS.

### LLM client (`backend/llm/`)

`LLMClient` is the single entry point. It selects a backend based on `provider.sdk_type`:
- `"openai"` (default) → `OpenAIBackend` using `openai` SDK (works for Qwen, DeepSeek, Doubao, OpenAI)
- `"anthropic"` → `AnthropicBackend` using `anthropic` SDK (used for MiniMax)

`complete()` returns just the text string. `complete_with_metadata()` returns a `CompletionResult` with token usage, elapsed time, and model name. Both methods retry on timeout/API errors up to `LLM_MAX_RETRIES`.

Provider configs are defined in `backend/llm/providers.py` (not only in `settings.py` — both files have copies; `providers.py` is what `LLMClient` actually reads).

### Roundtable app (`backend/roundtable/`)

**Data model:**
- `Discussion` — the session; tracks status (`setup→ready→active→paused→finished`), user role, token state, and round count
- `Character` — an AI persona (historical figure) tied to a discussion, with `viewpoints`, `language_style`, and `temporal_constraints` stored as JSON
- `Message` — individual messages in a discussion

**User roles** (set per discussion):
- `host` — controls flow; AI characters speak in turn automatically
- `participant` — user holds a "player token" and can `@CharacterName` to address specific characters
- `observer` — read-only

**WebSocket:** `DiscussionConsumer` (async, `channels.generic.websocket.AsyncWebsocketConsumer`) at `ws://…/ws/discussion/<id>/`. All real-time state is pushed through the channel group `discussion_<id>`.

**HTTP API:** REST endpoints under `/roundtable/api/` handle setup, character configuration, message sending (non-WS path), polling, profile management, and candidate queue management.

### Test configuration

Tests use `backend.config.settings_test` (set in root `pytest.ini`). The default `testpaths` is `tests/` at the project root.
