"""
Prometheus-compatible metrics library — stdlib only.

Provides Counter, Gauge, and Histogram metric types with thread-safe
label-based collection and Prometheus text exposition format output.
"""

from __future__ import annotations

import threading
import time
from typing import Sequence


class Counter:
    """Monotonically increasing counter with optional labels."""

    def __init__(self, name: str, help_text: str = "", label_names: Sequence[str] = ()) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = tuple(label_names)
        self._values: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def get(self, **labels: str) -> float:
        key = self._key(labels)
        with self._lock:
            return self._values.get(key, 0.0)

    def collect(self) -> list[str]:
        lines: list[str] = []
        if self.help_text:
            lines.append(f"# HELP {self.name} {self.help_text}")
        lines.append(f"# TYPE {self.name} counter")
        with self._lock:
            for key, value in sorted(self._values.items()):
                label_str = self._label_str(key)
                lines.append(f"{self.name}{label_str} {value}")
        return lines

    def _key(self, labels: dict[str, str]) -> tuple[str, ...]:
        return tuple(labels.get(n, "") for n in self.label_names)

    def _label_str(self, key: tuple[str, ...]) -> str:
        if not self.label_names:
            return ""
        pairs = [f'{n}="{v}"' for n, v in zip(self.label_names, key)]
        return "{" + ",".join(pairs) + "}"


class Gauge:
    """Value that can go up and down, with optional labels."""

    def __init__(self, name: str, help_text: str = "", label_names: Sequence[str] = ()) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = tuple(label_names)
        self._values: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] = value

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) - amount

    def get(self, **labels: str) -> float:
        key = self._key(labels)
        with self._lock:
            return self._values.get(key, 0.0)

    def collect(self) -> list[str]:
        lines: list[str] = []
        if self.help_text:
            lines.append(f"# HELP {self.name} {self.help_text}")
        lines.append(f"# TYPE {self.name} gauge")
        with self._lock:
            for key, value in sorted(self._values.items()):
                label_str = self._label_str(key)
                lines.append(f"{self.name}{label_str} {value}")
        return lines

    def _key(self, labels: dict[str, str]) -> tuple[str, ...]:
        return tuple(labels.get(n, "") for n in self.label_names)

    def _label_str(self, key: tuple[str, ...]) -> str:
        if not self.label_names:
            return ""
        pairs = [f'{n}="{v}"' for n, v in zip(self.label_names, key)]
        return "{" + ",".join(pairs) + "}"


class Histogram:
    """Histogram with configurable buckets and optional labels."""

    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

    def __init__(
        self,
        name: str,
        help_text: str = "",
        label_names: Sequence[str] = (),
        buckets: Sequence[float] | None = None,
    ) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = tuple(label_names)
        self.buckets = tuple(sorted(buckets or self.DEFAULT_BUCKETS))
        # Per-label-key: {bucket_bound: count}, _sum, _count
        self._bucket_counts: dict[tuple[str, ...], dict[float, int]] = {}
        self._sums: dict[tuple[str, ...], float] = {}
        self._counts: dict[tuple[str, ...], int] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            if key not in self._bucket_counts:
                self._bucket_counts[key] = {b: 0 for b in self.buckets}
                self._sums[key] = 0.0
                self._counts[key] = 0
            # Count in the smallest bucket that fits (collect will cumulate)
            for b in self.buckets:
                if value <= b:
                    self._bucket_counts[key][b] += 1
                    break
            self._sums[key] += value
            self._counts[key] += 1

    def collect(self) -> list[str]:
        lines: list[str] = []
        if self.help_text:
            lines.append(f"# HELP {self.name} {self.help_text}")
        lines.append(f"# TYPE {self.name} histogram")
        with self._lock:
            for key in sorted(self._bucket_counts.keys()):
                label_str = self._label_str(key)
                cumulative = 0
                for b in self.buckets:
                    cumulative += self._bucket_counts[key][b]
                    le_labels = self._label_str_with_le(key, b)
                    lines.append(f"{self.name}_bucket{le_labels} {cumulative}")
                inf_labels = self._label_str_with_le(key, "+Inf")
                lines.append(f"{self.name}_bucket{inf_labels} {self._counts[key]}")
                lines.append(f"{self.name}_sum{label_str} {self._sums[key]}")
                lines.append(f"{self.name}_count{label_str} {self._counts[key]}")
        return lines

    def _key(self, labels: dict[str, str]) -> tuple[str, ...]:
        return tuple(labels.get(n, "") for n in self.label_names)

    def _label_str(self, key: tuple[str, ...]) -> str:
        if not self.label_names:
            return ""
        pairs = [f'{n}="{v}"' for n, v in zip(self.label_names, key)]
        return "{" + ",".join(pairs) + "}"

    def _label_str_with_le(self, key: tuple[str, ...], le: float | str) -> str:
        pairs = [f'{n}="{v}"' for n, v in zip(self.label_names, key)]
        pairs.append(f'le="{le}"')
        return "{" + ",".join(pairs) + "}"


class MetricsRegistry:
    """Central registry that collects all metrics into Prometheus text format."""

    def __init__(self) -> None:
        self._metrics: list[Counter | Gauge | Histogram] = []
        self._lock = threading.Lock()

    def register(self, metric: Counter | Gauge | Histogram) -> None:
        with self._lock:
            self._metrics.append(metric)

    def collect(self) -> str:
        lines: list[str] = []
        with self._lock:
            metrics = list(self._metrics)
        for m in metrics:
            lines.extend(m.collect())
        lines.append("")  # trailing newline
        return "\n".join(lines)
