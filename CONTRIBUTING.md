# Contributing

## Development setup

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,auth]"
```

## Running the test suite

```bash
pytest -q
```

The suite spans:

- Unit tests for the HTTP parser, snowflake generator, and other pure modules
- Integration tests that spin up a real `Service` on a free localhost port
- Security tests for AES-GCM, JWT verify, CSRF, and the request parser's
  smuggling-rejection paths

## Linting

```bash
ruff check .
ruff format .
```

CI runs `ruff check`, `ruff format --check`, and the test matrix on
Python 3.11, 3.12, 3.13, and 3.14.

## Pull requests

- Branch from `main`.
- Add a regression test for any bug fix.
- Update `CHANGELOG.md` under the **Unreleased** section.
- Keep pull requests focused; prefer multiple small PRs over one large one.

## Releases

Releases are cut by tagging a GitHub Release. The `publish.yml` workflow
builds a sdist + wheel and publishes via PyPI Trusted Publishing (OIDC) — no
PyPI API token is involved.
