# Release

## Before tagging

1. Update the version in **both** `core/version.py` and `pyproject.toml`. They
   must match, and `CHANGELOG.md` must contain a `## [<version>]` heading;
   `tests/test_release_consistency.py` enforces both.
2. Add the release notes to `CHANGELOG.md`.
3. Run the same checks as CI:

```bash
uv sync --all-extras --dev
uv run ruff check .
QT_QPA_PLATFORM=offscreen uv run pytest
uv run python scripts/validate_skills.py
```

4. Commit, then create and push the tag:

```bash
git tag vX.Y.Z
git push origin main --tags
```

The tag must equal `v` + `core.version.__version__`; the release workflow
aborts otherwise.

## CI

`.github/workflows/python-app.yml` runs on every push and pull request to
`main` on Ubuntu, Windows and macOS:

- installs uv and (on Linux) the Qt runtime libraries;
- `uv sync --all-extras --dev`;
- `uv run ruff check .`;
- `uv run pytest` with `QT_QPA_PLATFORM=offscreen`;
- `uv run python scripts/validate_skills.py`.

## Release workflow

`.github/workflows/release.yml` triggers on `v*` tags and has three jobs:

| Job | Output |
|---|---|
| `dist` | `uv build` wheel + sdist, CycloneDX SBOM (`dist/sbom.cdx.json`, with a requirements fallback), uploaded as `python-dist`. |
| `bundle` | Per-OS PyInstaller bundle via `uv run python scripts/build.py`: Linux `.tar.gz`, Windows `.zip` plus Inno Setup `Setup.exe`, macOS `.dmg` via `create-dmg`, each with `SHA256SUMS-<platform>.txt`. |
| `publish` | Downloads all artifacts, combines the checksums into `SHA256SUMS.txt`, creates the GitHub release with generated notes, and publishes the wheel/sdist to PyPI using trusted publishing (`id-token: write`). Configure the trusted publisher once on pypi.org. |

`scripts/build.py` builds `dist/AI-Desktop-Assistant/` (or
`dist/AI Desktop Assistant.app` on macOS), archives it, and writes a checksum
file. It expects the PyInstaller spec at
`packaging/ai-desktop-assistant.spec`; the release workflow also references
`packaging/windows/installer.iss` and `packaging/macos/make_dmg.sh`. Those
packaging assets must be present in the checkout for a local or CI bundle.

## Local build

```bash
uv sync --all-extras
uv run python scripts/build.py
```

Chromium is **not** bundled. After installing the app, run:

```bash
playwright install chromium
```

## macOS signing and notarization

Set the repository secrets `APPLE_SIGN_ID`, `APPLE_ID`, `APPLE_TEAM_ID` and
`APPLE_APP_PASSWORD`. The release workflow passes them to
`packaging/macos/make_dmg.sh`. Without them the app is unsigned and macOS
requires right-click → **Open** the first time.

## PyPI

The package name and console script are declared in `pyproject.toml`:

- distribution: `ai-desktop-assistant`
- console script: `ai-desktop-assistant = main:main`

Trusted publishing uses OIDC; no long-lived PyPI token is stored in the
repository.
