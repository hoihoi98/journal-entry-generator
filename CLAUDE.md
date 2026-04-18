# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

## Running

```bash
python journal.py
```

## Architecture

This is a single-file CLI app (`journal.py`) that wraps the Anthropic Messages API to generate double-entry bookkeeping journal entries.

**Key design points:**

- `SYSTEM_PROMPT` is cached via `cache_control: ephemeral` — it's large (~3KB) and sent on every request, so prompt caching is intentional and load-bearing. Do not remove the `cache_control` block.
- `call_claude()` returns both the response text and the raw `usage` object; token counts (including cache hits/writes) are printed after each response for observability.
- The chart of accounts and double-entry rules are defined entirely inside the system prompt — there is no external data file.
- The model is pinned to `claude-sonnet-4-6` and `MAX_TOKENS = 1024`; the output format is strict (exactly two alternatives, no preamble).

## Claude API usage

- Uses `client.messages.create` with a system prompt array (not a plain string) to support `cache_control`.
- Handles `AuthenticationError`, `RateLimitError`, `BadRequestError`, `APIConnectionError`, and `APIStatusError` explicitly.
