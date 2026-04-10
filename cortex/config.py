from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from cortex.http_hardening import request_policy_for_mode
from cortex.release import API_VERSION, OPENAPI_VERSION, PROJECT_VERSION

try:  # pragma: no cover - exercised implicitly on Python 3.10
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python <3.11
    import tomli as tomllib

ALL_SCOPES = ("read", "write", "branch", "merge", "index", "prune")
VALID_SCOPES = set(ALL_SCOPES) | {"*", "admin"}
RUNTIME_MODES = ("local-single-user", "hosted-service")
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
HTTP_RUNTIME_SURFACES = {"api", "manus", "ui"}


def _split_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _as_optional_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return Path(raw)


def _path_from_config(value: str | Path | None, *, base_dir: Path | None) -> Path | None:
    path = _as_optional_path(value)
    if path is None:
        return None
    if path.is_absolute() or base_dir is None:
        return path
    return base_dir / path


def _normalize_namespace(value: str) -> str:
    namespace = value.strip().strip("/")
    return namespace or "*"


def _normalize_namespaces(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    raw_values = list(values or [])
    if not raw_values:
        return ("*",)
    normalized = tuple(dict.fromkeys(_normalize_namespace(item) for item in raw_values if str(item).strip()))
    return normalized or ("*",)


def _normalize_scopes(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    raw_values = [str(item).strip().lower() for item in (values or []) if str(item).strip()]
    if not raw_values:
        return ALL_SCOPES
    if "*" in raw_values or "admin" in raw_values:
        return ("admin",)
    invalid = sorted(set(raw_values) - VALID_SCOPES)
    if invalid:
        joined = ", ".join(invalid)
        raise ValueError(f"Unknown auth scope(s): {joined}")
    normalized = tuple(dict.fromkeys(raw_values))
    return normalized or ALL_SCOPES


def _normalize_server_host(value: str | None) -> str:
    host = str(value or "").strip()
    if not host:
        raise ValueError("Server host must be a non-empty string.")
    return host


def _normalize_server_port(value: Any) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Server port must be an integer between 0 and 65535: {value}") from exc
    if port < 0 or port > 65535:
        raise ValueError(f"Server port must be between 0 and 65535: {port}")
    return port


def _normalize_runtime_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower() or "local-single-user"
    if mode not in RUNTIME_MODES:
        raise ValueError(f"Runtime mode must be one of: {', '.join(RUNTIME_MODES)}.")
    return mode


def is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    if normalized in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _runtime_surface_label(surface: str) -> str:
    return {
        "api": "Cortex REST API",
        "manus": "Cortex Manus bridge",
        "ui": "Cortex UI",
    }.get(surface, f"Cortex {surface}")


def validate_runtime_security(
    *,
    surface: str,
    host: str,
    runtime_mode: str,
    api_keys: tuple["APIKeyConfig", ...] = (),
    namespace: str | None = None,
    allow_unsafe_bind: bool = False,
) -> None:
    normalized_surface = str(surface or "").strip().lower()
    if normalized_surface not in HTTP_RUNTIME_SURFACES:
        raise ValueError(f"Unknown runtime surface: {surface}")
    normalized_mode = _normalize_runtime_mode(runtime_mode)
    normalized_host = _normalize_server_host(host)
    if allow_unsafe_bind or is_loopback_host(normalized_host):
        return

    label = _runtime_surface_label(normalized_surface)
    if normalized_mode == "local-single-user":
        raise ValueError(
            f"Refusing to bind the {label} to a non-loopback host in local-single-user mode. "
            "Keep it on 127.0.0.1/localhost, switch to --runtime-mode hosted-service, "
            "or pass --allow-unsafe-bind to override."
        )

    if normalized_surface == "ui":
        raise ValueError(
            f"Refusing to bind the {label} to a non-loopback host in hosted-service mode. "
            "The UI does not yet enforce remote auth, so keep it on loopback or pass "
            "--allow-unsafe-bind to override."
        )

    if not api_keys:
        raise ValueError(
            f"Refusing to bind the {label} to a non-loopback host in hosted-service mode without API keys. "
            "Configure scoped auth keys or pass --allow-unsafe-bind to override."
        )

    if normalized_surface == "manus" and not str(namespace or "").strip():
        raise ValueError(
            f"Refusing to bind the {label} to a non-loopback host in hosted-service mode without a pinned namespace. "
            "Set `[mcp].namespace`, pass `--namespace`, or keep the bridge on loopback."
        )


@dataclass(slots=True)
class APIKeyConfig:
    name: str
    token: str
    scopes: tuple[str, ...] = ALL_SCOPES
    namespaces: tuple[str, ...] = ("*",)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "APIKeyConfig":
        name = str(payload.get("name", "")).strip()
        token = str(payload.get("token", "")).strip()
        if not name:
            raise ValueError("Each API key entry needs a non-empty 'name'.")
        if not token:
            raise ValueError(f"API key '{name}' is missing a non-empty token.")
        scopes = _normalize_scopes(list(payload.get("scopes") or []))
        namespaces = _normalize_namespaces(list(payload.get("namespaces") or []))
        return cls(name=name, token=token, scopes=scopes, namespaces=namespaces)

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "scopes": list(self.scopes),
            "namespaces": list(self.namespaces),
        }

    def allows_scope(self, scope: str) -> bool:
        return "admin" in self.scopes or scope in self.scopes

    def allows_namespace(self, namespace: str) -> bool:
        if "*" in self.namespaces:
            return True
        normalized = _normalize_namespace(namespace)
        return any(
            normalized == allowed or normalized.startswith(f"{allowed}/")
            for allowed in self.namespaces
            if allowed != "*"
        )

    def single_namespace(self) -> str | None:
        namespaces = [namespace for namespace in self.namespaces if namespace != "*"]
        if len(namespaces) == 1:
            return namespaces[0]
        return None


def _legacy_api_key(name: str, token: str, *, scopes: list[str] | tuple[str, ...] | None = None) -> APIKeyConfig:
    return APIKeyConfig(
        name=name,
        token=token.strip(),
        scopes=_normalize_scopes(list(scopes or ALL_SCOPES)),
        namespaces=("*",),
    )


@dataclass(slots=True)
class CortexSelfHostConfig:
    store_dir: Path = Path(".cortex")
    context_file: Path | None = None
    config_path: Path | None = None
    server_host: str = "127.0.0.1"
    server_port: int = 8766
    runtime_mode: str = "local-single-user"
    mcp_namespace: str | None = None
    api_keys: tuple[APIKeyConfig, ...] = field(default_factory=tuple)

    def sanitized(self) -> dict[str, Any]:
        return {
            "store_dir": str(self.store_dir),
            "context_file": str(self.context_file) if self.context_file else None,
            "config_path": str(self.config_path) if self.config_path else None,
            "server_host": self.server_host,
            "server_port": self.server_port,
            "runtime_mode": self.runtime_mode,
            "mcp_namespace": self.mcp_namespace,
            "api_keys": [item.to_safe_dict() for item in self.api_keys],
        }


@dataclass(slots=True)
class CortexStoreDiscovery:
    store_dir: Path
    source: str
    config_path: Path | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_dir": str(self.store_dir),
            "source": self.source,
            "config_path": str(self.config_path) if self.config_path else None,
            "warnings": list(self.warnings),
        }


def _candidate_config_path(
    *,
    explicit_path: str | Path | None,
    store_dir: str | Path | None,
    env: Mapping[str, str],
) -> tuple[Path | None, bool]:
    explicit = _as_optional_path(explicit_path)
    if explicit is not None:
        return explicit, True
    env_path = _as_optional_path(env.get("CORTEX_CONFIG"))
    if env_path is not None:
        return env_path, True
    base_store_dir = _as_optional_path(store_dir) or _as_optional_path(env.get("CORTEX_STORE_DIR")) or Path(".cortex")
    return Path(base_store_dir) / "config.toml", False


def _ancestry(start: Path) -> list[Path]:
    resolved = start.resolve()
    return [resolved, *resolved.parents]


def _discover_store_candidates(start: Path) -> list[Path]:
    return [candidate / ".cortex" for candidate in _ancestry(start) if (candidate / ".cortex").exists()]


def discover_cortex_store(
    *,
    start: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> CortexStoreDiscovery:
    env_map = env or os.environ
    explicit_env_store = _as_optional_path(env_map.get("CORTEX_STORE_DIR"))
    if explicit_env_store is not None:
        store_path = explicit_env_store if explicit_env_store.is_absolute() else (Path.cwd() / explicit_env_store)
        return CortexStoreDiscovery(store_dir=store_path.resolve(), source="env")

    start_path = Path(start or Path.cwd())
    store_candidates = _discover_store_candidates(start_path)
    warnings: list[str] = []
    if len(store_candidates) > 1:
        warnings.append(
            "Multiple Cortex stores were detected while walking upward from the current directory; using the nearest one."
        )

    for candidate in _ancestry(start_path):
        config_path = candidate / ".cortex" / "config.toml"
        if config_path.exists():
            config = load_selfhost_config(config_path=config_path, env={})
            return CortexStoreDiscovery(
                store_dir=config.store_dir.resolve(),
                source="discovered_config",
                config_path=config.config_path,
                warnings=tuple(warnings),
            )

    if store_candidates:
        return CortexStoreDiscovery(
            store_dir=store_candidates[0].resolve(),
            source="discovered_store",
            config_path=(store_candidates[0] / "config.toml").resolve()
            if (store_candidates[0] / "config.toml").exists()
            else None,
            warnings=tuple(warnings),
        )

    default_store = (start_path.resolve() / ".cortex").resolve()
    return CortexStoreDiscovery(
        store_dir=default_store,
        source="default",
        warnings=tuple(warnings),
    )


def resolve_cli_store_dir(
    store_dir: str | Path | None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> CortexStoreDiscovery:
    explicit = _as_optional_path(store_dir)
    if explicit is None:
        return discover_cortex_store(start=cwd or Path.cwd(), env=env)

    raw = str(store_dir).strip()
    if raw == ".cortex":
        return discover_cortex_store(start=cwd or Path.cwd(), env=env)

    base = cwd or Path.cwd()
    resolved = explicit if explicit.is_absolute() else (base / explicit)
    return CortexStoreDiscovery(store_dir=resolved.resolve(), source="cli")


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Config file did not parse as a TOML table: {path}")
    return payload


def _merge_api_keys(
    *sources: tuple[APIKeyConfig, ...],
) -> tuple[APIKeyConfig, ...]:
    merged: list[APIKeyConfig] = []
    by_name: dict[str, APIKeyConfig] = {}
    by_token: dict[str, APIKeyConfig] = {}
    for source in sources:
        for key in source:
            existing_name = by_name.get(key.name)
            existing_token = by_token.get(key.token)
            if existing_name is not None and existing_name.token != key.token:
                raise ValueError(f"Duplicate API key name with different tokens: {key.name}")
            if existing_token is not None and existing_token.name != key.name:
                raise ValueError(f"Duplicate API token used by multiple key names: {existing_token.name}, {key.name}")
            by_name[key.name] = key
            by_token[key.token] = key
    for key in by_name.values():
        merged.append(key)
    return tuple(merged)


def _keys_from_config(data: dict[str, Any]) -> tuple[APIKeyConfig, ...]:
    keys: list[APIKeyConfig] = []
    server_table = data.get("server") or {}
    if server_table and not isinstance(server_table, dict):
        raise ValueError("Config table [server] must be a TOML table.")
    legacy_token = str(server_table.get("api_key", "")).strip()
    if legacy_token:
        keys.append(
            APIKeyConfig(
                name="server-default",
                token=legacy_token,
                scopes=_normalize_scopes(list(server_table.get("api_key_scopes") or ALL_SCOPES)),
                namespaces=_normalize_namespaces(list(server_table.get("api_key_namespaces") or ["*"])),
            )
        )

    auth_table = data.get("auth") or {}
    if not isinstance(auth_table, dict):
        raise ValueError("Config table [auth] must be a TOML table.")
    raw_keys = auth_table.get("keys") or []
    if not isinstance(raw_keys, list):
        raise ValueError("Config key 'auth.keys' must be an array of tables.")
    keys.extend(APIKeyConfig.from_dict(item) for item in raw_keys)
    return tuple(keys)


def _keys_from_env(env: Mapping[str, str]) -> tuple[APIKeyConfig, ...]:
    keys: list[APIKeyConfig] = []
    json_payload = env.get("CORTEX_API_KEYS_JSON", "").strip()
    if json_payload:
        try:
            decoded = json.loads(json_payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"CORTEX_API_KEYS_JSON is not valid JSON: {exc.msg}") from exc
        if not isinstance(decoded, list):
            raise ValueError("CORTEX_API_KEYS_JSON must decode to a list of API key objects.")
        keys.extend(APIKeyConfig.from_dict(item) for item in decoded)
    legacy_token = env.get("CORTEX_API_KEY", "").strip()
    if legacy_token:
        keys.append(
            APIKeyConfig(
                name="env-default",
                token=legacy_token,
                scopes=_normalize_scopes(_split_csv(env.get("CORTEX_API_KEY_SCOPES")) or list(ALL_SCOPES)),
                namespaces=_normalize_namespaces(_split_csv(env.get("CORTEX_API_KEY_NAMESPACES")) or ["*"]),
            )
        )
    return tuple(keys)


def _keys_from_cli(api_key: str | None) -> tuple[APIKeyConfig, ...]:
    if not api_key:
        return ()
    return (_legacy_api_key("cli-default", api_key),)


def load_selfhost_config(
    *,
    store_dir: str | Path | None = None,
    context_file: str | Path | None = None,
    config_path: str | Path | None = None,
    server_host: str | None = None,
    server_port: int | None = None,
    runtime_mode: str | None = None,
    api_key: str | None = None,
    mcp_namespace: str | None = None,
    env: Mapping[str, str] | None = None,
) -> CortexSelfHostConfig:
    env_map = env or os.environ
    resolved_config_path, explicit = _candidate_config_path(
        explicit_path=config_path,
        store_dir=store_dir,
        env=env_map,
    )
    raw_config: dict[str, Any] = {}
    if resolved_config_path is not None and resolved_config_path.exists():
        raw_config = _load_toml(resolved_config_path)
    elif explicit and resolved_config_path is not None:
        raise ValueError(f"Config file not found: {resolved_config_path}")
    config_dir = resolved_config_path.parent if resolved_config_path and resolved_config_path.exists() else None

    runtime_table = raw_config.get("runtime") or {}
    if runtime_table and not isinstance(runtime_table, dict):
        raise ValueError("Config table [runtime] must be a TOML table.")
    server_table = raw_config.get("server") or {}
    if server_table and not isinstance(server_table, dict):
        raise ValueError("Config table [server] must be a TOML table.")
    mcp_table = raw_config.get("mcp") or {}
    if mcp_table and not isinstance(mcp_table, dict):
        raise ValueError("Config table [mcp] must be a TOML table.")

    configured_store_dir = (
        _as_optional_path(store_dir)
        or _as_optional_path(env_map.get("CORTEX_STORE_DIR"))
        or _path_from_config(runtime_table.get("store_dir"), base_dir=config_dir)
        or Path(".cortex")
    )
    configured_context_file = (
        _as_optional_path(context_file)
        or _as_optional_path(env_map.get("CORTEX_CONTEXT_FILE"))
        or _path_from_config(runtime_table.get("context_file"), base_dir=config_dir)
    )
    configured_runtime_mode = (
        str(runtime_mode).strip()
        if runtime_mode is not None
        else env_map.get("CORTEX_RUNTIME_MODE", "").strip()
        or str(runtime_table.get("mode", "")).strip()
        or "local-single-user"
    )
    configured_host = (
        str(server_host).strip()
        if server_host is not None
        else env_map.get("CORTEX_SERVER_HOST", "").strip() or str(server_table.get("host", "")).strip() or "127.0.0.1"
    )
    configured_port = (
        server_port
        if server_port is not None
        else env_map.get("CORTEX_SERVER_PORT", "") or server_table.get("port") or 8766
    )
    configured_mcp_namespace = (
        str(mcp_namespace).strip()
        if mcp_namespace is not None
        else env_map.get("CORTEX_MCP_NAMESPACE", "").strip() or str(mcp_table.get("namespace", "")).strip() or None
    )

    configured_keys = _merge_api_keys(
        _keys_from_config(raw_config),
        _keys_from_env(env_map),
        _keys_from_cli(api_key),
    )

    return CortexSelfHostConfig(
        store_dir=Path(configured_store_dir),
        context_file=configured_context_file.resolve() if configured_context_file else None,
        config_path=resolved_config_path.resolve() if resolved_config_path and resolved_config_path.exists() else None,
        server_host=_normalize_server_host(configured_host),
        server_port=_normalize_server_port(configured_port),
        runtime_mode=_normalize_runtime_mode(configured_runtime_mode),
        mcp_namespace=_normalize_namespace(configured_mcp_namespace) if configured_mcp_namespace else None,
        api_keys=configured_keys,
    )


def startup_diagnostics(config: CortexSelfHostConfig, *, mode: str) -> dict[str, Any]:
    store_dir = config.store_dir
    backend = "filesystem"
    if (store_dir / "cortex.db").exists():
        backend = "sqlite"
    elif (store_dir / "history.json").exists() or (store_dir / "versions").exists():
        backend = "filesystem"

    warnings: list[str] = []
    bind_scope = "loopback" if is_loopback_host(config.server_host) else "network"
    reverse_proxy_recommended = mode in {"server", "manus"} and config.runtime_mode == "hosted-service"
    if config.config_path is None:
        warnings.append("No config.toml loaded; using defaults and environment variables.")
    if not store_dir.exists():
        warnings.append("Store directory does not exist yet; Cortex will create it on first write.")
    if mode in {"server", "manus"} and not config.api_keys:
        if config.runtime_mode == "local-single-user":
            warnings.append("No API keys configured; local-single-user mode only permits safe loopback binds.")
        else:
            warnings.append("No API keys configured; hosted-service mode is only safe on loopback unless overridden.")
    if mode == "ui" and config.runtime_mode == "hosted-service":
        warnings.append(
            "The UI only provides browser session auth for loopback use; keep it on loopback unless you intentionally override it for API-key clients."
        )
    if mode in {"server", "manus"} and config.runtime_mode == "hosted-service":
        warnings.append(
            "Hosted-service deployments should run behind an HTTPS reverse proxy; Cortex does not terminate TLS itself."
        )
        if "*" in {namespace for key in config.api_keys for namespace in key.namespaces}:
            warnings.append(
                "Some API keys allow every namespace; prefer dedicated single-namespace keys for hosted-service deployments."
            )
        if bind_scope == "network" and mode == "manus" and not config.mcp_namespace:
            warnings.append(
                "Hosted-service Manus deployments should pin `mcp.namespace` so external clients cannot roam across namespaces."
            )
        if config.config_path is None:
            warnings.append(
                "Hosted-service deployments should use a persisted config.toml instead of relying on CLI or environment defaults alone."
            )
    if any(key.single_namespace() is None and "*" not in key.namespaces for key in config.api_keys):
        warnings.append("Some API keys cover multiple namespaces; those clients must send an explicit namespace.")
    if mode == "mcp" and not config.mcp_namespace:
        warnings.append("No default MCP namespace configured; clients may choose namespaces explicitly.")

    diagnostics = {
        "mode": mode,
        "project_version": PROJECT_VERSION,
        "api_version": API_VERSION,
        "openapi_version": OPENAPI_VERSION,
        "config_path": str(config.config_path) if config.config_path else None,
        "store_dir": str(store_dir),
        "store_exists": store_dir.exists(),
        "backend": backend,
        "context_file": str(config.context_file) if config.context_file else None,
        "server_host": config.server_host,
        "server_port": config.server_port,
        "bind_scope": bind_scope,
        "runtime_mode": config.runtime_mode,
        "mcp_namespace": config.mcp_namespace,
        "reverse_proxy_recommended": reverse_proxy_recommended,
        "auth_enabled": bool(config.api_keys),
        "api_key_count": len(config.api_keys),
        "api_keys": [item.to_safe_dict() for item in config.api_keys],
        "warnings": warnings,
    }
    if mode in {"server", "manus", "ui"}:
        diagnostics["request_policy"] = request_policy_for_mode(config.runtime_mode).to_dict()
    return diagnostics


def format_startup_diagnostics(config: CortexSelfHostConfig, *, mode: str) -> str:
    diagnostics = startup_diagnostics(config, mode=mode)
    lines = [
        f"Cortex {mode} diagnostics:",
        f"  Release:   {diagnostics['project_version']} (API {diagnostics['api_version']}, OpenAPI {diagnostics['openapi_version']})",
        f"  Store dir: {diagnostics['store_dir']}",
        f"  Backend:   {diagnostics['backend']}",
        f"  Runtime:   {diagnostics['runtime_mode']}",
    ]
    if diagnostics["config_path"]:
        lines.append(f"  Config:    {diagnostics['config_path']}")
    if diagnostics["context_file"]:
        lines.append(f"  Context:   {diagnostics['context_file']}")
    if mode in {"server", "manus", "ui"}:
        lines.append(f"  Listen:    {diagnostics['server_host']}:{diagnostics['server_port']}")
        lines.append(f"  Bind:      {diagnostics['bind_scope']}")
        if diagnostics["request_policy"]:
            policy = diagnostics["request_policy"]
            lines.append(
                "  Requests:  "
                + f"max {policy['max_body_bytes']} bytes, "
                + f"timeout {policy['read_timeout_seconds']}s, "
                + (
                    f"rate limit {policy['rate_limit_per_minute']}/min"
                    if policy["rate_limit_per_minute"]
                    else "rate limit disabled"
                )
            )
        if mode == "ui":
            session_note = "browser session token (loopback)"
            if diagnostics["auth_enabled"]:
                session_note += f" + {diagnostics['api_key_count']} scoped key(s)"
            lines.append(f"  Auth:      {session_note}")
        else:
            lines.append(
                "  Auth:      "
                + (f"{diagnostics['api_key_count']} scoped key(s)" if diagnostics["auth_enabled"] else "disabled")
            )
        if mode == "manus":
            lines.append(f"  Namespace: {diagnostics['mcp_namespace'] or '(unscoped)'}")
        if diagnostics["reverse_proxy_recommended"]:
            lines.append("  Deploy:    place Cortex behind an HTTPS reverse proxy")
        if mode != "ui" and diagnostics["api_keys"]:
            rendered_keys = ", ".join(
                f"{item['name']}[{','.join(item['scopes'])}]@{','.join(item['namespaces'])}"
                for item in diagnostics["api_keys"]
            )
            lines.append(f"  Keys:      {rendered_keys}")
    else:
        lines.append(f"  Namespace: {diagnostics['mcp_namespace'] or '(unscoped)'}")
    if diagnostics["warnings"]:
        lines.append("  Warnings:")
        lines.extend([f"    - {warning}" for warning in diagnostics["warnings"]])
    return "\n".join(lines)


__all__ = [
    "ALL_SCOPES",
    "APIKeyConfig",
    "CortexStoreDiscovery",
    "CortexSelfHostConfig",
    "HTTP_RUNTIME_SURFACES",
    "RUNTIME_MODES",
    "VALID_SCOPES",
    "discover_cortex_store",
    "format_startup_diagnostics",
    "is_loopback_host",
    "load_selfhost_config",
    "resolve_cli_store_dir",
    "startup_diagnostics",
    "validate_runtime_security",
]
