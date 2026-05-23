"""Weather-log ingest helpers — observations upsert + source-file registration.

These helpers own the DB-write half of the plugin. They are intentionally
kept in a separate module (rather than inlined in ``plugin.py``) so other
plugins emitting into the same ``observations`` table can import and reuse
them without pulling in the ``WeatherLogPlugin`` class itself.

The same pattern is used by the first-party ``raindrop``, ``spotify``, and
``google_fit`` plugins shipped under ``phdb.plugins/`` — each has its own
``ingest.py`` next to ``plugin.py``.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from phdb.records import HealthObservation


def register_source_file(
    conn: sqlite3.Connection,
    source_path: Path,
    *,
    source_kind: str = "weather_log",
    file_kind: str = "json",
) -> int:
    """Insert (or refresh) a ``source_files`` row for the given path.

    Mirrors the helper used by the first-party plugin exemplars
    (raindrop, spotify, goodreads). Phase 10 of the phdb Plugin
    Architecture plan lifts this into a shared
    ``phdb.core.sources`` helper; until then each plugin keeps its
    own copy to avoid coupling to in-flight framework code.
    """
    cur = conn.execute(
        """INSERT INTO source_files
           (source_path, source_org, file_kind, source_kind, session_uuid, ingested_at)
           VALUES (?, ?, ?, ?, NULL,
                   strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
           ON CONFLICT(source_path) DO UPDATE
             SET ingested_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
           RETURNING id""",
        (str(source_path), None, file_kind, source_kind),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def upsert_weather_observation(
    conn: sqlite3.Connection,
    source_file_id: int,
    rec: HealthObservation,
) -> int | None:
    """Insert one HealthObservation into the ``observations`` table.

    Idempotent on ``(source_file_id, raw_hash)`` via the
    ``idx_observations_dedup`` unique index. Returns the inserted row id
    on success, or ``None`` if the record was already present (dedup hit).
    """
    metadata = dict(rec.metadata)
    conditions = metadata.get("conditions", "")
    humidity = metadata.get("humidity")

    body_parts = [f"{rec.observation_type} = {rec.value} {rec.unit or ''}".strip()]
    if conditions:
        body_parts.append(f"conditions: {conditions}")
    if humidity is not None:
        body_parts.append(f"humidity: {humidity}%")
    body_text = " | ".join(body_parts)
    body_text_hash = hashlib.sha256(body_text.encode("utf-8")).hexdigest()

    subject = f"{rec.observation_type}: {rec.value}{rec.unit or ''}"[:200]
    observation_key = f"weather_log:{rec.provenance.raw_hash[:16]}"

    cur = conn.execute(
        """INSERT OR IGNORE INTO observations (
            schema_type, observation_key, type_identifier, subject,
            source_device, direction, date_observed, date_end,
            body_text, body_text_source, body_text_hash, is_bulk,
            bulk_signal, raw_hash, source_file_id
        ) VALUES (
            'Observation', ?, ?, ?, ?, 'self', ?, ?, ?,
            'weather-log-json', ?, 1, 'weather-log-daily-reading', ?, ?
        )""",
        (
            observation_key, rec.observation_type, subject,
            rec.source_device or "weather_log:self",
            rec.date_start, rec.date_end,
            body_text, body_text_hash, rec.provenance.raw_hash, source_file_id,
        ),
    )
    if cur.rowcount == 0:
        return None
    return cur.lastrowid
