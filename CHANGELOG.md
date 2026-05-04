# Changelog

All notable changes to this project will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.6.0] - 2026-05-03

This release is a hard rewrite of multiple defective subsystems identified in
a v0.5.11 audit. **Treat 0.5.11 as compromised** — the source distribution
shipped a real Ed25519 private key (`examples/localhost.key`) and the headline
encryption / authentication features were non-functional or actively
exploitable. Yank `mkfst==0.5.11` from PyPI before deploying 0.6.0.

### Security

- **AES-GCM rewrite.** `AESGCMFernet` previously generated a random key per
  message and prepended it to the ciphertext, providing no confidentiality.
  The new implementation derives a stable 32-byte key from
  `MERCURY_SYNC_AUTH_SECRET` via HKDF-SHA256, requires the secret to be
  configured (no more `"testtoken"` default), supports AAD, and emits a
  versioned wire format.
- **Authentication middleware now actually authenticates.** Pre-fix the
  `__run__` body was `try: pass` and any configured `Authentication(...)`
  silently allowed every request through. The middleware now invokes the
  configured authenticator, supports sync and async callables, attaches the
  resolved principal to the request context, and emits proper 401 / 403
  responses with optional `WWW-Authenticate`.
- **CSRF rewrite (`CRSF` typo renamed to `CSRF`).** Tokens are now AES-GCM
  authenticated payloads bound to the cookie name via the AEAD AAD field, with
  embedded issuance timestamp and configurable max-age. Cookie defaults are
  `Secure=True`, `SameSite=Lax`. Compression layer dropped (zstd-bomb risk
  with no upside on short tokens).
- **JWT verify hardening.** `algorithms` is now required and must be a
  non-empty list of allowed algorithm names. The verifier rejects mixed
  HMAC/asymmetric allowlists (alg-confusion bypass), explicitly rejects
  `alg=none` even when present in the allowlist, and defaults to requiring
  `exp` and `iat` claims (configurable via `options=`).
- **HTTP request smuggling and DoS hardening.** New
  `mkfst/connection/tcp/protocols/http_parser.py` is RFC 7230 strict: rejects
  Content-Length + Transfer-Encoding, rejects duplicate Host /
  Content-Length / Transfer-Encoding, rejects obs-fold (line-folded headers),
  caps body / chunk / header sizes via `MERCURY_SYNC_MAX_REQUEST_BODY_BYTES` /
  `MERCURY_SYNC_MAX_CHUNK_BYTES` / `MERCURY_SYNC_MAX_REQUEST_HEADER_BYTES`,
  parses chunk extensions and trailers correctly, and consumes exactly the
  Content-Length bytes (the previous `+1` slice ate a byte from the next
  pipelined request).
- **Per-connection state.** The `waiting_for_data` event used by the body
  reader was a single instance shared across all connections; concurrent body
  reads could feed each other's buffers. Moved to the protocol so each
  connection has its own.
- **CORS rewrite.** Invalid origin lists joined with `" | "`, `Max-Age`
  rendered as `"true"`/`"false"`, and the credentials + wildcard reflection
  bypass are all gone. New `Cors` middleware emits Vary: Origin on every
  varying response, refuses to construct with wildcard + credentials, and
  scrubs Allow-* headers from rejected preflights.
- **Examples cert/key regenerated.** `examples/localhost.{crt,key}` are now
  fresh self-signed dev material. The historical key shipped on PyPI is
  compromised; rotate any reuse.

### Correctness

- **Routing/fabricator cluster.** Headers parameter at handler position 0 was
  classified as a keyword arg (and crashed dispatch); query parsing was
  inverted (parsed only when the query was empty); the cookie branch was dead
  code (always-False guard); query-positional flag checked the wrong key
  type; positional argument insertion used `list.insert` and produced wrong
  ordering. All fixed; PEP 563 forward-reference annotations are now
  resolved via `get_type_hints`; HTTP header names are normalized
  (dash → underscore + lowercase) so handlers can declare `x_request_id: str`.
- **Response builder.** Status reason phrase is now derived per-status (was
  hardcoded `"OK"` for every response); bytes payloads no longer get
  `repr`-corrupted by an f-string round-trip; HEAD responses emit no body
  but advertise `Content-Length`.
- **Snowflake generator.** Instance bits are now masked to 10 bits before
  shifting (caller can't bleed into the timestamp region); sequence overflow
  spin-waits for the next millisecond instead of returning `None`; clock-step
  backwards blocks until wall-clock catches up; `from_snowflake` no longer
  passes an `epoch=` kwarg the constructor doesn't accept. The three
  duplicate copies under `mkfst.tasks.snowflake` and `mkfst.logging.snowflake`
  now re-export from the canonical `mkfst.snowflake`.
- **Tasks subsystem.** `Run.cancel()` / `abort()` now call `Task.cancel()`
  instead of the impossible `Task.set_result(None)`; the count-retention
  policy now keeps the most recent N runs (was deleting them); shell tasks
  shlex-quote each argument (no shell injection); the task runner no longer
  passes `signal.SIG_IGN` to `add_signal_handler` (which raised on every
  startup).
- **Caching.** Background `set_in_cache` tasks are tracked in a module-level
  `WeakSet` so CPython 3.11+ can't garbage-collect them mid-flight.
- **Logger.** Falls back to a thread-pool writer when stdout/stderr aren't
  pipe-able (e.g. captured by pytest, or redirected to a regular file);
  closes dup'd file handles on shutdown; no longer dups stderr inside the
  stdout helper.

### Packaging / CI

- Added `mkfst.__version__`, `py.typed` marker, and proper `Typing :: Typed`
  classifier (downstream type-checkers now recognize the package).
- Replaced unmaintained `orjson` (undeclared dep) with the already-declared
  `orjson` across the entire codebase.
- Removed the unused `pycryptodome` from the `[auth]` extra.
- Pinned dependency floors: `pydantic>=2.7,<3`, `cryptography>=42`,
  `msgspec>=0.18,<1`, etc.
- Replaced the publish workflow with a release-driven OIDC trusted-publishing
  flow (no more long-lived `PYPI_API_TOKEN`); added a separate test+lint+build
  CI workflow on the 3.11 / 3.12 / 3.13 / 3.14 matrix.
- Added project URLs (`Repository`, `Issues`, `Changelog`, `Documentation`).

### Removed

- The `mkfst.middleware.crsf` module (typo). Use `mkfst.middleware.csrf.CSRF`.

## [0.5.11] and earlier

Previous releases. **Yanked from PyPI** following the v0.6.0 audit.
