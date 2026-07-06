"""Reproducible HTTP layer: disk-cached GETs + a provenance log.

Every network fetch in the ingest layer goes through `http_get`, which makes a
build:
  - **reproducible** — the same cache snapshot yields identical raw bytes, so the
    downstream transforms (all deterministic) yield identical artifacts;
  - **auditable** — every fetch records (tag, url, bytes, cache hit, UTC time) in
    `PROVENANCE`, dumped into the build manifest;
  - **resilient** — a source outage during a scheduled refresh can fall back to
    the last cached copy instead of corrupting the page.

Modes (all optional env vars):
  SUBSUELO_CACHE     cache dir (default: <cwd>/out/cache)
  SUBSUELO_REFRESH   1 → ignore cache, refetch + overwrite (scheduled updates)
  SUBSUELO_OFFLINE   1 → never hit the network; serve cache only (raise if miss)
  SUBSUELO_NO_CACHE  1 → bypass the cache entirely (always fetch, never store)

A fetch that fails while refreshing automatically falls back to a stale cached
copy if one exists (logged with `stale: true`), so one flaky endpoint doesn't
sink the whole build.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

import requests

_UA = {"User-Agent": "subsuelo/0.3 (+https://example.org)"}
_TIMEOUT = 120

# provenance for the current build — reset per region by build.py, then dumped
PROVENANCE: list = []


def reset_provenance() -> None:
    PROVENANCE.clear()


def dump_provenance(path: str) -> None:
    with open(path, "w") as f:
        json.dump(list(PROVENANCE), f, indent=2)


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def cache_dir() -> str:
    d = os.environ.get("SUBSUELO_CACHE") or os.path.join(os.getcwd(), "out", "cache")
    os.makedirs(d, exist_ok=True)
    return d


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _key(url: str, params) -> str:
    raw = url + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def http_get(url: str, params=None, headers=None, timeout=None, tag: str | None = None) -> bytes:
    """Cached GET returning the response body as bytes. Raises on network error
    or non-2xx (callers keep their existing try/except for graceful fallback).

    Caching is keyed by url+sorted(params), so paged requests and per-bbox drill
    fetches each cache independently.
    """
    path = os.path.join(cache_dir(), _key(url, params))
    use_cache = not _flag("SUBSUELO_NO_CACHE")
    refresh = _flag("SUBSUELO_REFRESH")
    offline = _flag("SUBSUELO_OFFLINE")

    if use_cache and not refresh and os.path.exists(path):
        with open(path, "rb") as f:
            body = f.read()
        PROVENANCE.append({"tag": tag, "url": url, "bytes": len(body), "cache": True})
        return body

    if offline:
        if os.path.exists(path):
            with open(path, "rb") as f:
                body = f.read()
            PROVENANCE.append({"tag": tag, "url": url, "bytes": len(body),
                               "cache": True, "offline": True})
            return body
        raise RuntimeError(f"offline mode and no cache for {url}")

    try:
        r = requests.get(url, params=params, headers=headers or _UA,
                         timeout=timeout or _TIMEOUT)
        r.raise_for_status()
        body = r.content
    except Exception:
        # a refresh that fails falls back to any stale copy so the build survives
        if use_cache and os.path.exists(path):
            with open(path, "rb") as f:
                body = f.read()
            PROVENANCE.append({"tag": tag, "url": url, "bytes": len(body),
                               "cache": True, "stale": True})
            return body
        raise

    if use_cache:
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, path)   # atomic — a killed build never leaves a half file
    PROVENANCE.append({"tag": tag, "url": url, "bytes": len(body),
                       "cache": False, "fetched_at": _utc()})
    return body
