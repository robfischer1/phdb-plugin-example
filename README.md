# phdb-plugin-example

A worked, runnable example of a standalone third-party [phdb](https://github.com/anthropic/phdb) source plugin.

This is not a real data source. It exists to show, end to end, what a pip-installable phdb plugin looks like when it lives outside the phdb tree: manifest, ABC implementation, entry-point registration, tests, and packaging. Copy this repo's shape when porting a real source into a standalone plugin.

## What it does

The plugin walks a directory for files named `weather-YYYY-MM-DD.json`, one daily reading per file:

```json
{
  "date": "2026-05-23",
  "temp_c": 18.5,
  "humidity": 65,
  "conditions": "partly cloudy"
}
```

Each file becomes one `Observation` row in phdb's existing `observations` typed table (`type_identifier = "weather.temp_c"`), with humidity + conditions folded into `body_text` for FTS. No schema changes required. Re-running over the same directory is a no-op — dedup keys off `(source_file_id, raw_hash)`.

## Install

```bash
uv pip install phdb-plugin-example
```

Once installed, the plugin is discoverable via the `phdb.plugins` entry-point group declared in `pyproject.toml` — no phdb-side configuration needed.

## Verify

```bash
phdb plugin list
# Source plugins:
#   weather_log                    v0.1.0     entry_point
```

If `weather_log` does not appear, the entry-point declaration didn't register at install time. Re-install with `uv pip install --force-reinstall phdb-plugin-example` and check `importlib.metadata.entry_points(group='phdb.plugins')`.

```bash
phdb plugin describe weather_log
# Plugin: weather_log
#   Version:     0.1.0
#   Kind:        source
#   Entry point: phdb_plugin_example.plugin:WeatherLogPlugin
#   ...
```

## Use

```bash
phdb plugin ingest weather_log ~/path/to/weather/logs
```

`phdb plugin ingest` walks the directory via the plugin's `discover`, parses each file with `parse`, and persists each record via `ingest_row` — the standard contract path. The DB write is transactional and idempotent; pointing at the same directory twice yields zero new rows.

## Project structure

```
src/phdb_plugin_example/
  plugin.toml   — declarative manifest (name, version, kind, emitted @types)
  plugin.py     — WeatherLogPlugin: discover / parse / ingest_row / run
  ingest.py     — DB-write helpers (upsert_weather_observation, register_source_file)
tests/
  conftest.py   — fresh migrated SQLite DB per test (via phdb's MigrationRunner)
  test_plugin.py
  fixtures/     — three hand-authored weather-YYYY-MM-DD.json files
```

## Architecture notes

The interesting seams to notice, in order of "read this first":

- `plugin.toml` is the declarative manifest. The phdb loader parses it without importing the plugin's code, so a broken plugin can't block the rest of the catalogue.
- `[project.entry-points."phdb.plugins"]` in `pyproject.toml` is what makes phdb see the plugin after `pip install`. The key (`weather_log`) is the name users type at the CLI; the value is the dotted path to the plugin class.
- `WeatherLogPlugin` subclasses `PhdbSourcePlugin` (an ABC) — missing `@abstractmethod`s raise `TypeError` at instantiation, so contract drift fails loudly.
- The plugin re-uses `HealthObservation` from `phdb.records` rather than minting its own typed record. The framework only knows the records it ships; new shapes go in upstream phdb, not in plugins.
- The plugin writes into the existing `observations` table (migration 0019). New `@type`s need a schema + migration in upstream phdb first — that's a one-time framework change, not a plugin change.
- `ingest.py` is split out from `plugin.py` on purpose: other plugins emitting into the same `observations` table can import its helpers without pulling in `WeatherLogPlugin` itself. First-party plugins (`raindrop`, `spotify`, `google_fit`) follow the same split.

See <https://github.com/anthropic/phdb/blob/main/docs/plugins.md> for the full contract spec, the worked porting walkthrough, and the manifest reference.

## Development

```bash
git clone ssh://git@forgejo.notusmi.com:30143/rob/phdb-plugin-example.git
cd phdb-plugin-example
uv sync
uv run pytest tests/ -x -q
```

Ruff is configured in `pyproject.toml` (`target-version = "py311"`, line-length 99):

```bash
uv run ruff check .
```

Tests spin up a fresh SQLite DB per test via phdb's `MigrationRunner` (`tests/conftest.py`), then run the plugin against the bundled fixtures under `tests/fixtures/`. One test (`TestEntryPointDiscovery`) requires the package actually installed (`uv pip install -e .`) and self-skips otherwise.

## License

MIT — see `LICENSE`.
