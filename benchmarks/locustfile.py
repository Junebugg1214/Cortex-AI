"""
Locust load test for Cortex CaaS API.

Run with::

    locust -f benchmarks/locustfile.py --host http://127.0.0.1:8421

    # With authentication:
    locust -f benchmarks/locustfile.py --host http://127.0.0.1:8421 \\
        --token YOUR_GRANT_TOKEN

Scenarios are imported from benchmarks/scenarios/.
"""

from __future__ import annotations

from locust import HttpUser, between, events

from benchmarks.scenarios.auth_flow import AuthFlowScenario
from benchmarks.scenarios.mixed import MixedScenario
from benchmarks.scenarios.read_heavy import ReadHeavyScenario
from benchmarks.scenarios.write_heavy import WriteHeavyScenario

# Store the token globally so all users can access it
_AUTH_TOKEN: str | None = None


@events.init_command_line_parser.add_listener
def add_custom_args(parser):
    parser.add_argument(
        "--token",
        type=str,
        default="",
        help="Bearer token for authenticated endpoints",
    )


@events.init.add_listener
def on_init(environment, **kwargs):
    global _AUTH_TOKEN
    token = environment.parsed_options.token if hasattr(environment.parsed_options, "token") else ""
    if token:
        _AUTH_TOKEN = token


def _get_auth_headers() -> dict[str, str]:
    """Return Authorization header if a token was provided."""
    if _AUTH_TOKEN:
        return {"Authorization": f"Bearer {_AUTH_TOKEN}"}
    return {}


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


class AuthFlowUser(AuthFlowScenario, HttpUser):
    """Simulates authenticated API flows (context, versions, grants)."""
    wait_time = between(0.5, 2)
    weight = 2
