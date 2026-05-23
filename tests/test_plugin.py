"""Tests for the WeatherLogPlugin example third-party plugin.

Coverage:

- Plugin instantiates with ``manifest=None`` (test convenience).
- Plugin loads its real manifest via ``load_manifest``.
- ``discover`` yields exactly the three bundled fixture files.
- ``parse`` yields a ``HealthObservation`` with the expected fields.
- ``ingest_row`` inserts into the ``observations`` table.
- Idempotent rerun produces zero new rows.
- ``discover_plugins()`` surfaces the plugin under the
  ``phdb.plugins`` entry-point group once the package is installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from phdb.core.plugin import discover_plugins, load_manifest
from phdb.db import connect
from phdb.records import HealthObservation

from phdb_plugin_example import WeatherLogPlugin

MANIFEST_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "phdb_plugin_example"
    / "plugin.toml"
)


def _plugin_from_manifest() -> WeatherLogPlugin:
    """Build a plugin instance using the on-disk manifest."""
    manifest = load_manifest(MANIFEST_PATH)
    return WeatherLogPlugin(manifest)


# ---------------------------------------------------------------------------
# Contract instantiation
# ---------------------------------------------------------------------------


class TestInstantiation:
    def test_instantiates_with_none_manifest(self) -> None:
        # Test convenience — no manifest on disk, plugin still works.
        plugin = WeatherLogPlugin(manifest=None)
        assert isinstance(plugin, WeatherLogPlugin)

    def test_loads_manifest_from_disk(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)
        assert manifest.name == "weather_log"
        assert manifest.kind == "source"
        assert manifest.source is not None
        assert manifest.source.emits == ["Observation"]

    def test_manifest_attached_to_plugin(self) -> None:
        plugin = _plugin_from_manifest()
        assert plugin.name == "weather_log"
        assert plugin.kind == "source"


# ---------------------------------------------------------------------------
# discover / parse
# ---------------------------------------------------------------------------


class TestDiscover:
    def test_yields_three_fixture_files(self, fixtures_dir: Path) -> None:
        plugin = _plugin_from_manifest()
        results = list(plugin.discover(fixtures_dir))
        assert len(results) == 3
        for path, kind in results:
            assert path.name.startswith("weather-")
            assert path.suffix == ".json"
            assert kind == "weather_log"

    def test_yields_single_file_when_pointed_at_file(
        self, fixtures_dir: Path
    ) -> None:
        plugin = _plugin_from_manifest()
        target = fixtures_dir / "weather-2026-05-20.json"
        results = list(plugin.discover(target))
        assert results == [(target, "weather_log")]

    def test_skips_non_matching_files(self, tmp_path: Path) -> None:
        # A directory holding *.json that doesn't match the
        # weather-*.json pattern must produce zero yields.
        (tmp_path / "unrelated.json").write_text("{}")
        plugin = _plugin_from_manifest()
        assert list(plugin.discover(tmp_path)) == []


class TestParse:
    def test_yields_health_observation_with_expected_fields(
        self, fixtures_dir: Path
    ) -> None:
        plugin = _plugin_from_manifest()
        path = fixtures_dir / "weather-2026-05-21.json"
        records = list(plugin.parse(path))
        assert len(records) == 1
        rec = records[0]
        assert isinstance(rec, HealthObservation)
        assert rec.observation_type == "weather.temp_c"
        assert rec.date_start == "2026-05-21"
        assert rec.value == pytest.approx(19.8)
        assert rec.unit == "C"
        assert rec.source_device == "weather_log:self"
        # Metadata folds humidity + conditions
        meta = dict(rec.metadata)
        assert meta.get("conditions") == "partly cloudy"
        assert meta.get("humidity") == "58"
        # Provenance carries a stable raw_hash + the source path
        assert rec.provenance.source_path == str(path)
        assert rec.provenance.raw_hash
        assert len(rec.provenance.raw_hash) == 64  # sha256


# ---------------------------------------------------------------------------
# ingest_row + idempotency
# ---------------------------------------------------------------------------


class TestIngest:
    def test_run_inserts_into_observations(
        self, fresh_db: Path, fixtures_dir: Path
    ) -> None:
        plugin = _plugin_from_manifest()
        with connect(fresh_db) as conn:
            report = plugin.run(fixtures_dir, conn)
            count = conn.execute(
                "SELECT COUNT(*) FROM observations"
            ).fetchone()[0]
        assert report.rows_yielded == 3
        assert report.rows_inserted == 3
        assert report.rows_skipped == 0
        assert count == 3

    def test_idempotent_rerun(
        self, fresh_db: Path, fixtures_dir: Path
    ) -> None:
        plugin = _plugin_from_manifest()
        with connect(fresh_db) as conn:
            plugin.run(fixtures_dir, conn)
        with connect(fresh_db) as conn:
            report = plugin.run(fixtures_dir, conn)
            count = conn.execute(
                "SELECT COUNT(*) FROM observations"
            ).fetchone()[0]
        assert report.rows_yielded == 3
        assert report.rows_inserted == 0
        assert report.rows_skipped == 3
        assert count == 3  # unchanged

    def test_observation_columns_populated(
        self, fresh_db: Path, fixtures_dir: Path
    ) -> None:
        plugin = _plugin_from_manifest()
        with connect(fresh_db) as conn:
            plugin.run(fixtures_dir, conn)
            row = conn.execute(
                """SELECT schema_type, type_identifier, date_observed,
                          body_text, body_text_source, source_device,
                          is_bulk, bulk_signal
                   FROM observations
                   ORDER BY date_observed
                   LIMIT 1"""
            ).fetchone()
        assert row["schema_type"] == "Observation"
        assert row["type_identifier"] == "weather.temp_c"
        assert row["date_observed"] == "2026-05-20"
        assert "weather.temp_c" in row["body_text"]
        assert "overcast" in row["body_text"]
        assert row["body_text_source"] == "weather-log-json"
        assert row["source_device"] == "weather_log:self"
        assert row["is_bulk"] == 1
        assert row["bulk_signal"] == "weather-log-daily-reading"


# ---------------------------------------------------------------------------
# Entry-point discovery (integration — requires `pip install -e .`)
# ---------------------------------------------------------------------------


class TestEntryPointDiscovery:
    def test_discoverable_via_entry_points(self) -> None:
        """The plugin appears under ``phdb.plugins`` once installed.

        Skipped when the package isn't installed in the active env —
        running ``uv pip install -e .`` in this repo (or installing
        ``phdb-plugin-example`` into phdb's venv) makes this pass.
        """
        names = {d.name for d in discover_plugins()}
        if "weather_log" not in names:
            pytest.skip(
                "phdb-plugin-example not installed in this env; run "
                "`uv pip install -e .` to enable entry-point discovery"
            )
        descriptors = [d for d in discover_plugins() if d.name == "weather_log"]
        assert len(descriptors) >= 1
        descriptor = descriptors[0]
        assert descriptor.manifest.kind == "source"
        assert descriptor.manifest.source is not None
        assert descriptor.manifest.source.emits == ["Observation"]
        # No validation issues — Observation is in the phdb schemas registry.
        assert descriptor.issues == []
