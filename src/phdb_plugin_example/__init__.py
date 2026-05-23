"""phdb-plugin-example — example third-party phdb source plugin.

Canonical reference shape for authors building a standalone
pip-installable phdb plugin. Ingests a directory of daily weather log
JSON files (one reading per file) into the ``observations`` typed
table. See https://github.com/anthropic/phdb/blob/main/docs/plugins.md
for the contract spec.
"""

from __future__ import annotations

from phdb_plugin_example.plugin import WeatherLogPlugin

__all__ = ["WeatherLogPlugin"]
