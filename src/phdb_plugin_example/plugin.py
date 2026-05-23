"""WeatherLogPlugin — example third-party phdb source plugin.

Walks a directory of ``weather-YYYY-MM-DD.json`` files (one daily
reading per file) and ingests each as an ``Observation`` row into
phdb's existing ``observations`` typed table.

The plugin demonstrates the end-to-end ``PhdbSourcePlugin`` contract
without depending on any in-tree phdb machinery beyond what a
third-party author already has access to:

- ``discover(root)`` walks the filesystem for ``weather-*.json`` files
  and yields ``(path, source_kind)`` tuples — one per daily reading.
- ``parse(path)`` reads + decodes one JSON file into a single
  ``HealthObservation`` record (the standard typed intermediate for
  the ``Observation`` ``@type``).
- ``ingest_row(conn, record)`` upserts the record into the
  ``observations`` table via the local ``upsert_weather_observation``
  helper; idempotent on ``(source_file_id, raw_hash)``.
- ``register_cli(parser)`` / ``register_tools(server)`` are no-op stubs
  — the plugin works out of the box via the generic
  ``phdb plugin ingest weather_log <path>`` command.
- ``run(source_path, conn, settings)`` is the convenience runner that
  ``phdb plugin ingest`` invokes; mirrors the shape of the first-party
  raindrop / spotify / goodreads exemplars.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from phdb.core.plugin import PhdbSourcePlugin
from phdb.records import HealthObservation, Provenance

from phdb_plugin_example.ingest import (
    register_source_file,
    upsert_weather_observation,
)

if TYPE_CHECKING:
    from phdb.core.plugin.manifest import PluginManifest
    from phdb.settings import Settings


@dataclass
class IngestSummary:
    """Result of one ``run()`` call — mirrors the IngestSummary shape used
    by the first-party plugin exemplars."""

    source_path: str
    source_file_id: int = 0
    rows_yielded: int = 0
    rows_inserted: int = 0
    rows_skipped: int = 0
    errors: list[str] = field(default_factory=list)


class WeatherLogPlugin(PhdbSourcePlugin):
    """Weather-log JSON ingester (example third-party plugin)."""

    SOURCE_KIND = "weather_log"
    FILE_KIND = "json"
    BATCH_SIZE = 100

    def __init__(self, manifest: PluginManifest | None = None) -> None:
        # The PhdbPlugin base stores the manifest on self; subclasses that
        # override __init__ must call super().__init__ first per the
        # contract docs. We accept ``None`` to support test construction
        # without a manifest on disk.
        super().__init__(manifest)  # type: ignore[arg-type]

    # ----------------------- PhdbSourcePlugin contract ---------------------

    def discover(self, root: Path) -> Iterator[tuple[Path, str]]:
        """Walk ``root``; yield ``(path, source_kind)`` for every weather log file.

        Accepts either a single JSON file or a directory containing
        ``weather-*.json`` files. Generic ``*.json`` would over-match in
        directories holding mixed sources — the filename pattern is the
        discipline knob.
        """
        if root.is_file():
            if root.name.startswith("weather-") and root.suffix.lower() == ".json":
                yield root, self.SOURCE_KIND
            return
        for path in sorted(root.rglob("weather-*.json")):
            yield path, self.SOURCE_KIND

    def parse(self, path: Path) -> Iterator[HealthObservation]:
        """Yield one HealthObservation from a single weather log JSON file.

        The on-disk shape is intentionally minimal::

            {
                "date": "2026-05-23",
                "temp_c": 18.5,
                "humidity": 65,
                "conditions": "partly cloudy"
            }

        We emit one ``HealthObservation`` per file with
        ``observation_type = "weather.temp_c"`` and the humidity +
        conditions tucked into ``metadata`` so the upsert can fold them
        into ``body_text`` without losing structure.
        """
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))

        date = str(data.get("date") or "")
        temp_c = data.get("temp_c")
        humidity = data.get("humidity")
        conditions = data.get("conditions") or ""

        if not date or temp_c is None:
            # Skip malformed/incomplete files silently — the plugin
            # contract treats parse as a generator, so yielding nothing
            # is the canonical "no records here" signal.
            return

        # Stable raw_hash over the canonical JSON payload — re-running
        # over the same file produces the same hash and dedup fires.
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        raw_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        metadata: tuple[tuple[str, str], ...] = tuple(
            (k, str(v))
            for k, v in (
                ("conditions", conditions),
                ("humidity", humidity),
            )
            if v not in (None, "")
        )

        yield HealthObservation(
            provenance=Provenance(
                source_path=str(path),
                raw_hash=raw_hash,
                source_byte_offset=0,
                source_byte_length=len(raw),
            ),
            observation_type="weather.temp_c",
            date_start=date,
            value=float(temp_c),
            unit="C",
            date_end=None,
            source_device="weather_log:self",
            metadata=metadata,
        )

    def ingest_row(
        self,
        conn: sqlite3.Connection,
        record: HealthObservation,
        *,
        source_file_id: int | None = None,
    ) -> int | None:
        """Persist one HealthObservation to the ``observations`` table.

        Returns the inserted row id or ``None`` on a dedup hit. The
        idempotency guarantee comes from the ``idx_observations_dedup``
        unique index over ``(source_file_id, raw_hash)``.
        """
        sf_id = source_file_id if source_file_id is not None else 0
        return upsert_weather_observation(conn, sf_id, record)

    def register_cli(self, parser: Any) -> None:
        """No plugin-specific subcommands — use ``phdb plugin ingest weather_log``."""
        return None

    def register_tools(self, server: Any) -> None:
        """No plugin-specific MCP tools."""
        return None

    # ------------------------- Convenience runner --------------------------

    def run(
        self,
        source_path: Path,
        conn: sqlite3.Connection,
        settings: Settings | None = None,
    ) -> IngestSummary:
        """End-to-end ingest of one root path (file or directory).

        The standard shape ``phdb plugin ingest`` invokes — discover →
        parse → ingest_row, with a single source_files row per file
        (so re-running is cheap and the dedup index does the work).
        """
        report = IngestSummary(source_path=str(source_path))

        batch_count = 0
        last_sf_id: int | None = None

        for path, _kind in self.discover(source_path):
            source_file_id = register_source_file(
                conn, path,
                source_kind=self.SOURCE_KIND, file_kind=self.FILE_KIND,
            )
            last_sf_id = source_file_id

            for record in self.parse(path):
                report.rows_yielded += 1
                row_id = self.ingest_row(
                    conn, record, source_file_id=source_file_id,
                )
                if row_id is None:
                    report.rows_skipped += 1
                else:
                    report.rows_inserted += 1

                batch_count += 1
                if batch_count >= self.BATCH_SIZE:
                    conn.commit()
                    batch_count = 0

        conn.commit()
        # Report the last source_file_id touched — callers usually pass a
        # directory, so this matches the spotify/goodreads convention.
        report.source_file_id = last_sf_id or 0
        return report
