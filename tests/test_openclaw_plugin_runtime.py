from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

from cortex.channel_runtime import ChannelMessage, TelegramAdapter
from cortex.cli import main
from cortex.service.service import MemoryService
from cortex.storage import get_storage_backend


def _seed_portability(base: Path) -> tuple[Path, Path]:
    home_dir = base / "home"
    home_dir.mkdir()
    project_dir = base / "project"
    project_dir.mkdir()
    store_dir = base / ".cortex"
    export_path = base / "chatgpt-export.txt"
    export_path.write_text(
        (
            "My name is Casey. "
            "I use Python, FastAPI, and Next.js. "
            "I prefer direct answers. "
            "I support customers across Telegram and WhatsApp."
        ),
        encoding="utf-8",
    )
    previous_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home_dir)
    try:
        rc = main(
            [
                "portable",
                str(export_path),
                "--to",
                "all",
                "--project",
                str(project_dir),
                "--store-dir",
                str(store_dir),
                "--format",
                "json",
            ]
        )
    finally:
        if previous_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = previous_home
    assert rc == 0
    return project_dir, store_dir


def _seed_brainpack_and_mount_openclaw(project_dir: Path, store_dir: Path) -> None:
    source = project_dir / "brainpack.md"
    source.write_text(
        (
            "# Support Brainpack\n\n"
            "Casey supports Telegram and WhatsApp customers.\n"
            "Cortex Brainpacks are portable domain minds.\n"
            "Next.js deployment questions are common.\n"
        ),
        encoding="utf-8",
    )
    assert main(["pack", "init", "support-pack", "--store-dir", str(store_dir), "--format", "json"]) == 0
    assert (
        main(
            [
                "pack",
                "ingest",
                "support-pack",
                str(source),
                "--store-dir",
                str(store_dir),
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "pack",
                "compile",
                "support-pack",
                "--store-dir",
                str(store_dir),
                "--suggest-questions",
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "pack",
                "mount",
                "support-pack",
                "--to",
                "openclaw",
                "--project",
                str(project_dir),
                "--store-dir",
                str(store_dir),
                "--openclaw-store-dir",
                str(store_dir),
                "--smart",
                "--format",
                "json",
            ]
        )
        == 0
    )


def _seed_mind_and_mount_openclaw(project_dir: Path, store_dir: Path) -> None:
    source = project_dir / "mind-brainpack.md"
    source.write_text(
        (
            "# Support Mind\n\n"
            "Casey is building a portable support mind for OpenClaw.\n"
            "OpenClaw support threads should inherit persistent support context.\n"
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "mind",
                "init",
                "support-mind",
                "--kind",
                "agent",
                "--owner",
                "cortex",
                "--store-dir",
                str(store_dir),
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert main(["pack", "init", "support-mind-pack", "--store-dir", str(store_dir), "--format", "json"]) == 0
    assert (
        main(
            [
                "pack",
                "ingest",
                "support-mind-pack",
                str(source),
                "--store-dir",
                str(store_dir),
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "pack",
                "compile",
                "support-mind-pack",
                "--store-dir",
                str(store_dir),
                "--suggest-questions",
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "mind",
                "attach-pack",
                "support-mind",
                "support-mind-pack",
                "--always-on",
                "--target",
                "openclaw",
                "--target",
                "chatgpt",
                "--store-dir",
                str(store_dir),
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "mind",
                "mount",
                "support-mind",
                "--to",
                "openclaw",
                "--task",
                "support",
                "--project",
                str(project_dir),
                "--store-dir",
                str(store_dir),
                "--openclaw-store-dir",
                str(store_dir),
                "--smart",
                "--format",
                "json",
            ]
        )
        == 0
    )


def test_openclaw_plugin_package_packs_cleanly(tmp_path):
    root = Path(__file__).resolve().parents[1]
    package_dir = root / "examples" / "openclaw-plugin"
    env = os.environ.copy()
    env["NPM_CONFIG_CACHE"] = str(tmp_path / ".npm-cache")
    result = subprocess.run(  # noqa: S603
        ["npm", "pack", "--json"],
        cwd=package_dir,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    tarball = package_dir / payload[0]["filename"]
    assert tarball.exists()
    with tarfile.open(tarball, "r:gz") as archive:
        names = set(archive.getnames())
    tarball.unlink()
    assert "package/package.json" in names
    assert "package/openclaw.plugin.json" in names
    assert "package/config.schema.json" in names
    assert "package/src/index.js" in names
    assert "package/src/service.js" in names
    assert "package/src/hooks.js" in names
    assert "package/src/identity.js" in names


def test_openclaw_plugin_runtime_boots_managed_cortex_and_seeds_memory(tmp_path):
    root = Path(__file__).resolve().parents[1]
    plugin_entry = (root / "examples" / "openclaw-plugin" / "src" / "index.js").resolve()
    project_dir, store_dir = _seed_portability(tmp_path)
    _seed_brainpack_and_mount_openclaw(project_dir, store_dir)

    event = {
        "platform": "telegram",
        "workspaceId": "support-bot",
        "conversationId": "chat-42",
        "userId": "tg-123",
        "phoneNumber": "+1 555 0101",
        "displayName": "Casey",
        "text": "Do you support Next.js deployments?",
        "messageId": "msg-1",
    }
    script = tmp_path / "run_openclaw_plugin_test.mjs"
    script.write_text(
        """
const { default: plugin } = await import(process.env.CORTEX_PLUGIN_ENTRY);

const hooks = new Map();
let serviceDef = null;
const logs = [];

const api = {
  logger: {
    info(message) { logs.push({ level: "info", message: String(message) }); },
    warn(message) { logs.push({ level: "warn", message: String(message) }); },
    error(message) { logs.push({ level: "error", message: String(message) }); },
  },
  getConfig() {
    return JSON.parse(process.env.CORTEX_PLUGIN_CONFIG);
  },
  registerService(definition) {
    serviceDef = definition;
  },
  on(name, handler) {
    hooks.set(name, handler);
  },
};

plugin.register(api);
await serviceDef.start();

const event = JSON.parse(process.env.CORTEX_PLUGIN_EVENT);
const ctx = { agent: { workspaceDir: process.env.CORTEX_PROJECT_DIR } };

await hooks.get("message_received")(event, ctx);
const prompt = await hooks.get("before_prompt_build")(event, ctx);
await hooks.get("agent_end")(event, ctx);
await serviceDef.stop();

process.stdout.write(JSON.stringify({ prompt, logs }));
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["CORTEX_PLUGIN_ENTRY"] = plugin_entry.as_uri()
    env["CORTEX_PROJECT_DIR"] = str(project_dir)
    env["CORTEX_PLUGIN_EVENT"] = json.dumps(event)
    env["CORTEX_PLUGIN_CONFIG"] = json.dumps(
        {
            "storeDir": str(store_dir),
            "configPath": str(store_dir / "config.toml"),
            "transport": "managed-child",
            "mcpCommand": sys.executable,
            "mcpArgs": ["-m", "cortex.mcp"],
            "defaultTarget": "chatgpt",
            "smartRouting": True,
            "autoSeedThreads": True,
            "maxContextChars": 1200,
            "failOpen": False,
        }
    )
    result = subprocess.run(  # noqa: S603
        ["node", str(script)],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    prompt = payload["prompt"]

    assert "prependContext" in prompt
    assert "python" in prompt["prependContext"].lower()
    assert "next.js" in prompt["prependContext"].lower()
    assert "mounted brainpack (support-pack)" in prompt["prependContext"].lower()
    assert "portable domain minds" in prompt["prependContext"].lower()

    identity = TelegramAdapter().resolve_identity(
        ChannelMessage(
            platform="telegram",
            workspace_id="support-bot",
            conversation_id="chat-42",
            user_id="tg-123",
            text="Do you support Next.js deployments?",
            display_name="Casey",
            phone_number="+1 555 0101",
            project_dir=str(project_dir),
            metadata={"message_id": "msg-1"},
        )
    )
    service = MemoryService(store_dir=store_dir, backend=get_storage_backend(store_dir))
    subject_node = service.get_node(
        node_id=f"contact/{identity.subject_key}",
        ref=identity.subject_namespace,
        namespace=identity.subject_namespace,
    )
    thread_node = service.get_node(
        node_id=f"thread/{identity.conversation_key}",
        ref=identity.conversation_namespace,
        namespace=identity.conversation_namespace,
    )

    assert subject_node["node"]["label"] == "Casey"
    assert thread_node["node"]["label"] == "Telegram thread chat-42"


def test_openclaw_plugin_runtime_injects_mounted_mind_context(tmp_path):
    root = Path(__file__).resolve().parents[1]
    plugin_entry = (root / "examples" / "openclaw-plugin" / "src" / "index.js").resolve()
    project_dir, store_dir = _seed_portability(tmp_path)
    _seed_mind_and_mount_openclaw(project_dir, store_dir)

    event = {
        "platform": "telegram",
        "workspaceId": "support-bot",
        "conversationId": "chat-77",
        "userId": "tg-321",
        "phoneNumber": "+1 555 0102",
        "displayName": "Casey",
        "text": "Can this support agent keep context across threads?",
        "messageId": "msg-2",
    }
    script = tmp_path / "run_openclaw_plugin_mind_test.mjs"
    script.write_text(
        """
const { default: plugin } = await import(process.env.CORTEX_PLUGIN_ENTRY);

const hooks = new Map();
let serviceDef = null;

const api = {
  logger: {
    info() {},
    warn() {},
    error() {},
  },
  getConfig() {
    return JSON.parse(process.env.CORTEX_PLUGIN_CONFIG);
  },
  registerService(definition) {
    serviceDef = definition;
  },
  on(name, handler) {
    hooks.set(name, handler);
  },
};

plugin.register(api);
await serviceDef.start();

const event = JSON.parse(process.env.CORTEX_PLUGIN_EVENT);
const ctx = { agent: { workspaceDir: process.env.CORTEX_PROJECT_DIR } };

await hooks.get("message_received")(event, ctx);
const prompt = await hooks.get("before_prompt_build")(event, ctx);
await serviceDef.stop();

process.stdout.write(JSON.stringify({ prompt }));
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["CORTEX_PLUGIN_ENTRY"] = plugin_entry.as_uri()
    env["CORTEX_PROJECT_DIR"] = str(project_dir)
    env["CORTEX_PLUGIN_EVENT"] = json.dumps(event)
    env["CORTEX_PLUGIN_CONFIG"] = json.dumps(
        {
            "storeDir": str(store_dir),
            "configPath": str(store_dir / "config.toml"),
            "transport": "managed-child",
            "mcpCommand": sys.executable,
            "mcpArgs": ["-m", "cortex.mcp"],
            "defaultTarget": "chatgpt",
            "smartRouting": True,
            "autoSeedThreads": True,
            "maxContextChars": 1200,
            "failOpen": False,
        }
    )
    result = subprocess.run(  # noqa: S603
        ["node", str(script)],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    prepend = payload["prompt"]["prependContext"]

    assert "mounted mind (support-mind)" in prepend.lower()
    assert "portable support mind" in prepend.lower() or "support mind" in prepend.lower()
