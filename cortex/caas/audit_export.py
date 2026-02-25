"""
Audit log export utilities — JSON and CSV formatters, time-range parsing.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone


def parse_since(since_str: str) -> datetime:
    """Parse a relative time string like '7d', '24h', '30m' into a UTC datetime.

    Supported suffixes: d (days), h (hours), m (minutes).
    """
    match = re.fullmatch(r"(\d+)([dhm])", since_str.strip())
    if not match:
        raise ValueError(f"Invalid time format: {since_str!r} (expected e.g. '7d', '24h', '30m')")
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "d":
        delta = timedelta(days=amount)
    elif unit == "h":
        delta = timedelta(hours=amount)
    else:
        delta = timedelta(minutes=amount)
    return datetime.now(timezone.utc) - delta


def filter_since(entries: list[dict], since_dt: datetime) -> list[dict]:
    """Filter audit entries to only those on or after *since_dt*."""
    result = []
    since_iso = since_dt.isoformat()
    for entry in entries:
        ts = entry.get("timestamp", "")
        if ts >= since_iso:
            result.append(entry)
    return result


def export_json(entries: list[dict]) -> str:
    """Export audit entries as indented JSON."""
    return json.dumps(entries, indent=2, default=str)


def export_csv(entries: list[dict]) -> str:
    """Export audit entries as CSV with header row."""
    if not entries:
        return "sequence_id,timestamp,event_type,actor,request_id,details,prev_hash,entry_hash\n"
    fieldnames = ["sequence_id", "timestamp", "event_type", "actor",
                  "request_id", "details", "prev_hash", "entry_hash"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for entry in entries:
        row = dict(entry)
        # Serialize details dict as JSON string
        if isinstance(row.get("details"), dict):
            row["details"] = json.dumps(row["details"], default=str)
        writer.writerow(row)
    return output.getvalue()
