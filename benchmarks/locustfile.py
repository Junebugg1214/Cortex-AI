"""
Locust load test for Cortex CaaS API.

Run with::

    locust -f benchmarks/locustfile.py --host http://127.0.0.1:8421

Scenarios are imported from benchmarks/scenarios/.
"""

from __future__ import annotations

from locust import HttpUser, between, task

from benchmarks.scenarios.mixed import MixedScenario
from benchmarks.scenarios.read_heavy import ReadHeavyScenario
from benchmarks.scenarios.write_heavy import WriteHeavyScenario


class ReadHeavyUser(ReadHeavyScenario, HttpUser):
    """Simulates read-heavy API usage (80% reads, 20% writes)."""
    wait_time = between(0.5, 2)
    weight = 3


class WriteHeavyUser(WriteHeavyScenario, HttpUser):
    """Simulates write-heavy API usage (30% reads, 70% writes)."""
    wait_time = between(0.5, 2)
    weight = 1


class MixedUser(MixedScenario, HttpUser):
    """Simulates balanced API usage (50/50 reads and writes)."""
    wait_time = between(0.5, 2)
    weight = 2
