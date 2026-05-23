# phdb-plugin-example

A worked example of a standalone third-party
[phdb](https://github.com/anthropic/phdb) source plugin. It ingests a
directory of daily weather log JSON files (one reading per file) into
the existing `observations` typed table — no schema changes required.

This repository exists to show, end to end, what a pip-installable
phdb plugin looks like when it lives outside the phdb tree. The full
contract (manifest, ABC, discovery, tests, distribution) is documented
at <https://github.com/anthropic/phdb/blob/main/docs/plugins.md>.

## What it does

The plugin walks a directory for files named `weather-YYYY-MM-DD.json`
with the shape:

```json
{
  "date": "2026-05-23",
  "temp_c": 18.5,
  "humidity": 65,
  "conditions": "partly cloudy"
}
```

Each file becomes one `Observation` row in `observations`
(`type_identifier = "weather.temp_c"`), with humidity + conditions
folded into `body_text` for FTS. Re-running over the same directory is
a no-op thanks to the standard `(source_file_id, raw_hash)` dedup
index.

## Install

```bash
uv pip install phdb-plugin-example
```

Once installed, the plugin is discoverable via the `phdb.plugins`
entry-point group — no phdb-side configuration needed.

## Verify

```bash
phdb plugin list
# Source plugins:
#   weather_log                    v0.1.0     entry_point
```

If `weather_log` does not appear, the entry-point declaration in
`pyproject.toml` did not register at install time — re-install with
`uv pip install --force-reinstall phdb-plugin-example` and check
`importlib.metadata.entry_points(group='phdb.plugins')`.

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

`phdb plugin ingest` walks the directory via the plugin's `discover`,
parses each file with `parse`, and persists each record via
`ingest_row` — the standard contract path. The DB write is
transactional and idempotent; pointing at the same directory twice
yields zero new rows.

## Architecture notes

This is an example demonstrating the phdb plugin contract — a
real-world plugin would replace the weather-log shape with whatever
source format it owns and re-use the same scaffolding. The interesting
seams to notice:

- `plugin.toml` is the declarative manifest. The phdb loader parses
  it without importing the plugin's code, so a broken plugin can't
  block the rest of the catalogue.
- The `[project.entry-points."phdb.plugins"]` table in
  `pyproject.toml` is what makes phdb see the plugin after
  `pip install`. The key (`weather_log`) is the name users type at the
  CLI; the value is the dotted path to the plugin class.
- `WeatherLogPlugin` subclasses `PhdbSourcePlugin` (an ABC) — missing
  `@abstractmethod`s raise `TypeError` at instantiation, so contract
  drift fails loudly.
- The plugin re-uses `HealthObservation` from `phdb.records` rather
  than minting its own typed record. The framework only knows the
  records it ships; new shapes go in upstream phdb, not in plugins.
- The plugin writes into `observations` (migration 0019) — an
  existing typed table. New `@type`s need a schema + migration in
  upstream phdb first; that's a one-time framework change, not a
  plugin change.

See <https://github.com/anthropic/phdb/blob/main/docs/plugins.md> for
the full contract spec, the worked porting walkthrough, and the
manifest reference.

## Development

```bash
git clone <repo-url> phdb-plugin-example
cd phdb-plugin-example
uv sync
uv run pytest tests/ -x -q
```

Tests use phdb's `MigrationRunner` to spin up a fresh SQLite DB per
test (`tests/conftest.py`). The DB is populated against the bundled
fixtures under `tests/fixtures/` (three hand-authored
`weather-YYYY-MM-DD.json` files).

## License

MIT — see `LICENSE`.
