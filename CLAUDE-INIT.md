# CLAUDE-INIT.md

Codebase orientation for AI sessions. Posture and governance live in AGENTS.md (furnace-compiled); this file is the repo-specific map, read on demand.

Note: this repo has no `AGENTS.md` of its own — it is a standalone, self-contained example package, not wired into the Forge fleet's compose/star infrastructure (no `star.toml`, `Dockerfile`, `compose.yaml`, or CI workflow present).

## Overview

`phdb-plugin-example` is a reference implementation of a third-party, pip-installable **source plugin** for `personal-history-db` (the `phdb` package/CLI). It ingests daily weather-log JSON files into phdb's existing `observations` typed table. The domain (weather) is a stand-in — the point of the repo is the *plugin contract shape*: manifest + ABC + entry-point + tests + packaging, copy-pasteable for anyone porting a real source into a standalone phdb plugin.

Role in the fleet: documentation-as-code / worked example, not a running service. It is a companion to phdb's own `docs/plugins.md` contract spec and to the `phdb-plugin-scaffolder` skill (which scaffolds new plugins in this same shape from CLI args).

Single commit as of this writing (`feat: example third-party phdb plugin — weather log ingester`) — treat this as an early-stage, essentially-frozen reference artifact rather than an actively iterated service.

## Architecture / module map

```
src/phdb_plugin_example/
  __init__.py   — re-exports WeatherLogPlugin as the package's public surface
  plugin.toml   — declarative manifest: name, version, kind=source, entry_point,
                  emits=["Observation"], facets_projected=["Time"]
  plugin.py     — WeatherLogPlugin(PhdbSourcePlugin): discover / parse / ingest_row /
                  register_cli / register_tools / run(); IngestSummary dataclass
  ingest.py     — DB-write helpers, deliberately split from plugin.py so other
                  plugins targeting `observations` can reuse them without importing
                  WeatherLogPlugin: register_source_file(), upsert_weather_observation()
tests/
  conftest.py       — fresh_db fixture: fresh migrated SQLite DB per test via
                      phdb.migrations.runner.MigrationRunner; fixtures_dir fixture
  test_plugin.py    — TestInstantiation, TestDiscover, TestParse, TestIngest,
                      TestEntryPointDiscovery (self-skips unless package is
                      `pip install -e .`'d into the active env)
  fixtures/         — 3 hand-authored weather-YYYY-MM-DD.json files (2026-05-20/21/22)
pyproject.toml  — setuptools build; package under src/; entry-point registration lives here
plugin.toml     — (see above) manifest phdb's loader parses without importing code
LICENSE         — MIT
```

No `docs/` directory in this repo — the contract spec it implements lives upstream in phdb (`docs/plugins.md`), not here.

## Entry points

- **CLI (via installed phdb)**: `phdb plugin list`, `phdb plugin describe weather_log`, `phdb plugin ingest weather_log <path>`. This repo does not ship its own CLI binary — `register_cli()` and `register_tools()` in `plugin.py` are no-op stubs.
- **Python entry-point group**: `phdb.plugins` (declared in `pyproject.toml` under `[project.entry-points."phdb.plugins"]`), key `weather_log` → `phdb_plugin_example.plugin:WeatherLogPlugin`. This is what makes `phdb` discover the plugin after `pip install`, via `phdb.core.plugin.discover_plugins()`.
- **Programmatic**: `from phdb_plugin_example import WeatherLogPlugin`. Key methods on the instance: `discover(root) -> Iterator[(Path, str)]`, `parse(path) -> Iterator[HealthObservation]`, `ingest_row(conn, record, *, source_file_id=None) -> int | None`, `run(source_path, conn, settings=None) -> IngestSummary`.

## Build / Test / Run

All commands as declared in `pyproject.toml` — do not execute without instruction; documented here for reference:

```bash
uv sync                          # install deps (personal-history-db>=0.4.0, +dev: pytest, ruff)
uv run pytest tests/ -x -q       # run tests (testpaths = ["tests"] per [tool.pytest.ini_options])
uv run ruff check .              # lint (target-version py311, line-length 99, E501 ignored)
uv pip install -e .              # local editable install — required for TestEntryPointDiscovery to run (not skip)
uv pip install phdb-plugin-example   # install from a built distribution
```

Build backend: `setuptools.build_meta` (requires `setuptools>=68.0`). Package discovery is `where = ["src"]`. `plugin.toml` is shipped as package data (`[tool.setuptools.package-data]`).

No CI workflow file present in this repo (no `.forgejo/` or `.github/`) — tests run manually / locally.

## Conventions and gotchas

- **Import name vs. PyPI name vs. CLI name**: the pip package is `personal-history-db` (the dependency in `pyproject.toml`), but the importable module and CLI binary are both `phdb`. Don't confuse `phdb-plugin-example` (this repo) with `phdb`/`personal-history-db` (the upstream framework this plugin extends) or `personal-history-db` the MCP server tool namespace.
- **Manifest-before-import discipline**: `plugin.toml` must be parseable by phdb's loader *without* importing `plugin.py`. A syntax error in the manifest is caught in isolation; it doesn't take down plugin discovery for the rest of the catalogue.
- **ABC contract enforcement**: `WeatherLogPlugin(PhdbSourcePlugin)` — any missing `@abstractmethod` implementation raises `TypeError` at instantiation, not at call time. This is the intended fail-loud behavior for contract drift; don't work around it with a partial subclass.
- **Records are framework-owned**: the plugin emits `HealthObservation` (from `phdb.records`) rather than defining its own record type. New observation *shapes* still fit this record; genuinely new `@type`s require a schema + migration upstream in phdb, not a plugin-side change.
- **Migration dependency**: writes target the `observations` table (phdb migration 0019). This plugin assumes that migration is already applied by the host phdb install; tests apply it locally via `MigrationRunner(conn).apply_pending()` in `conftest.py`.
- **Idempotency mechanism**: dedup is `INSERT OR IGNORE` keyed on the `(source_file_id, raw_hash)` unique index (`idx_observations_dedup`), not application-level dedup logic. `raw_hash` is a SHA-256 over the canonicalized (sorted-keys, compact-separator) JSON payload — re-serializing must stay stable or dedup silently breaks.
- **Malformed input handling**: `parse()` silently yields nothing (no exception) when `date` or `temp_c` is missing — a generator yielding zero records is the plugin contract's canonical "no records here" signal, not an error path.
- **`discover()` dual-mode**: accepts either a single file (checked by filename prefix + suffix) or a directory (globs `weather-*.json` via `rglob`, sorted). Generic `*.json` globbing is deliberately avoided to not over-match in mixed-source directories.
- **`ingest.py` split is a reuse seam**: DB-write helpers live outside `plugin.py` specifically so sibling plugins writing into the same `observations` table can import them directly. Follow this split if adding a second plugin here.
- **Repo is a template, not a library to depend on**: don't add this package as a runtime dependency elsewhere — fork/copy its shape instead when building a real plugin.
- Working tree at last inspection was on branch `docs/readme-refresh` (single upstream commit on `main`); check `git branch` / `git log` before assuming branch state.

## Related repos

- **`personal-history-db` (phdb)** — the upstream framework this plugin extends: ships `PhdbSourcePlugin` (`phdb.core.plugin`), `HealthObservation`/`Provenance` (`phdb.records`), `MigrationRunner` (`phdb.migrations.runner`), `connect()` (`phdb.db`), and the `observations` table schema/migrations this plugin writes into. Referenced in this repo's README at `https://github.com/anthropic/phdb` (docs path `docs/plugins.md` for the full contract spec) — verify that location before trusting it; it was not independently confirmed while writing this doc.
- First-party plugin exemplars mentioned in-repo but not present here: `raindrop`, `spotify`, `google_fit`, `goodreads` — these ship inside phdb itself (`phdb.plugins/`) and follow the same `plugin.py` + `ingest.py` split.
- Git remote for this repo: `ssh://git@forgejo.notusmi.com:30143/rob/phdb-plugin-example.git`.
