from __future__ import annotations

from cortex.config import load_selfhost_config
from cortex.http_hardening import HTTPRequestPolicy, SQLiteRateLimiter, build_rate_limiter


class _FakeClock:
    def __init__(self, value: float) -> None:
        self.value = float(value)

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += float(seconds)


def test_sqlite_rate_limiter_persists_blocked_bucket_after_restart(tmp_path):
    store_dir = tmp_path / ".cortex"
    db_path = store_dir / "ratelimit.sqlite"
    clock = _FakeClock(1_800_000_000.0)

    limiter = SQLiteRateLimiter(2, db_path, clock=clock)
    assert limiter.hit("client-a") is True
    assert limiter.hit("client-a") is True
    assert limiter.hit("client-a") is False

    restarted = SQLiteRateLimiter(2, db_path, clock=clock)
    assert restarted.hit("client-a") is False

    clock.advance(61.0)
    assert restarted.hit("client-a") is True


def test_ratelimit_backend_config_selects_sqlite_factory(tmp_path):
    store_dir = tmp_path / ".cortex"
    store_dir.mkdir()
    config_path = store_dir / "config.toml"
    config_path.write_text(
        """
[runtime]
store_dir = "."

[server.ratelimit]
backend = "sqlite"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_selfhost_config(store_dir=store_dir, config_path=config_path, env={})
    limiter = build_rate_limiter(
        HTTPRequestPolicy(rate_limit_per_minute=1),
        store_dir=config.store_dir,
        backend=config.ratelimit_backend,
    )

    assert config.ratelimit_backend == "sqlite"
    assert isinstance(limiter, SQLiteRateLimiter)
    assert (store_dir / "ratelimit.sqlite").exists()
