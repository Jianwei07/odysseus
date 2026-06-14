#!/bin/sh
# Headroom sidecar entrypoint.
#
# Two processes:
#   1. `headroom proxy` (loopback :8787) — holds the CompressionStore that
#      headroom_retrieve reads from. Background.
#   2. `mcp-proxy` — fronts the stdio `headroom mcp serve` and exposes it over
#      SSE at http://0.0.0.0:8096/sse for Odysseus to connect to. Foreground.
#
# `--` stops mcp-proxy option parsing so `--proxy-url` is passed to the wrapped
# `headroom mcp serve`, not consumed by mcp-proxy.
set -eu

HEADROOM_PROXY_PORT="${HEADROOM_PROXY_PORT:-8787}"
HEADROOM_SSE_PORT="${HEADROOM_SSE_PORT:-8096}"

headroom proxy --host 127.0.0.1 --port "${HEADROOM_PROXY_PORT}" &

exec mcp-proxy --host=0.0.0.0 --port="${HEADROOM_SSE_PORT}" -- \
  headroom mcp serve --proxy-url "http://127.0.0.1:${HEADROOM_PROXY_PORT}"
