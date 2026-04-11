from __future__ import annotations

import json
import re

import pytest

import cortex.cli as cli_module
from cortex.cli import ADVANCED_HELP_NOTE, FIRST_CLASS_COMMANDS, build_parser, main
from cortex.graph import CortexGraph, Node, make_node_id_with_tag


def _listed_commands(help_text: str) -> set[str]:
    commands: set[str] = set()
    for line in help_text.splitlines():
        match = re.match(r"^\s{4,}([a-z][a-z0-9-]*)\s{2,}", line)
        if match:
            commands.add(match.group(1))
    return commands


def test_default_help_is_first_class_and_mind_first():
    help_text = build_parser().format_help()
    commands = _listed_commands(help_text)

    assert set(FIRST_CLASS_COMMANDS).issubset(commands)
    assert {
        "portable",
        "remember",
        "build",
        "audit",
        "merge",
        "governance",
        "remote",
        "backup",
        "server",
        "mcp",
        "ui",
        "memory",
        "scan",
        "sync",
        "status",
    }.isdisjoint(commands)
    assert "Start Here:" in help_text
    assert "Surface Map:" in help_text
    assert "Runtime / admin" in help_text
    assert "cortex connect manus" in help_text
    assert "cortex help init" in help_text
    assert ADVANCED_HELP_NOTE in help_text


def test_help_all_shows_full_command_list(capsys):
    rc = main(["--help-all"])
    out = capsys.readouterr().out
    commands = _listed_commands(out)

    assert rc == 0
    assert set(FIRST_CLASS_COMMANDS).issubset(commands)
    assert {
        "portable",
        "remember",
        "build",
        "audit",
        "merge",
        "governance",
        "remote",
        "backup",
        "server",
        "mcp",
        "ui",
        "memory",
        "scan",
        "sync",
        "status",
    }.issubset(commands)
    assert ADVANCED_HELP_NOTE not in out


def test_compatibility_subcommand_help_labels_are_visible(capsys):
    parser = build_parser(show_all_commands=True)

    with pytest.raises(SystemExit, match="0"):
        parser.parse_args(["portable", "--help"])
    portable_help = capsys.readouterr().out

    with pytest.raises(SystemExit, match="0"):
        parser.parse_args(["server", "--help"])
    server_help = capsys.readouterr().out

    assert "Compatibility command for legacy portability-first context sync" in portable_help
    assert "Compatibility alias for `cortex serve api`" in server_help


def test_first_class_subcommand_help_explains_product_surfaces(capsys):
    parser = build_parser()

    with pytest.raises(SystemExit, match="0"):
        parser.parse_args(["init", "--help"])
    init_help = capsys.readouterr().out

    with pytest.raises(SystemExit, match="0"):
        parser.parse_args(["connect", "--help"])
    connect_help = capsys.readouterr().out

    with pytest.raises(SystemExit, match="0"):
        parser.parse_args(["serve", "--help"])
    serve_help = capsys.readouterr().out

    with pytest.raises(SystemExit, match="0"):
        parser.parse_args(["doctor", "--help"])
    doctor_help = capsys.readouterr().out

    assert "cortex help init" in init_help
    assert "--owner" not in init_help
    assert "--kind" not in init_help
    assert "--namespace" not in init_help
    assert "--default-policy" not in init_help
    assert "--no-mind" not in init_help
    assert "runtime wiring for Cortex without materializing Mind state yet" in connect_help
    assert "Use `cortex mind mount` to materialize Cortex state" in connect_help
    assert "Runtime / admin surfaces:" in serve_help
    assert "day-to-day workflows usually start with `cortex init`" in serve_help
    assert "store, config, and runtime drift" in doctor_help
    assert "cortex doctor --fix-store" in doctor_help
    assert "cortex doctor --portability" in doctor_help
    assert "--portability" in doctor_help


def _write_graph(path):
    graph = CortexGraph()
    graph.add_node(
        Node(
            id=make_node_id_with_tag("Marc Saint-Jour", "identity"),
            label="Marc Saint-Jour",
            tags=["identity"],
            confidence=0.9,
            brief="Founder and operator.",
        )
    )
    path.write_text(json.dumps(graph.export_v5(), indent=2), encoding="utf-8")


def test_server_and_mcp_commands_print_compatibility_hints(tmp_path, capsys):
    store_dir = tmp_path / ".cortex"

    server_rc = main(["server", "--store-dir", str(store_dir), "--check"])
    server_streams = capsys.readouterr()
    mcp_rc = main(["mcp", "--store-dir", str(store_dir), "--check"])
    mcp_streams = capsys.readouterr()

    assert server_rc == 0
    assert "cortex serve api" in server_streams.err
    assert mcp_rc == 0
    assert "cortex serve mcp" in mcp_streams.err


def test_argparse_required_argument_errors_include_task_hints(capsys):
    parser = build_parser()

    with pytest.raises(SystemExit, match="2"):
        parser.parse_args(["mind", "status"])
    status_error = capsys.readouterr().err

    assert "the following arguments are required: name" in status_error
    assert "Try: cortex mind list" in status_error


def test_unknown_first_arg_routes_to_migrate(monkeypatch, tmp_path):
    called = {}
    input_path = tmp_path / "chat-export.json"
    input_path.write_text("{}", encoding="utf-8")

    def fake_run_migrate(args):
        called["input_file"] = args.input_file
        called["to"] = args.to
        return 73

    monkeypatch.setattr(cli_module, "run_migrate", fake_run_migrate)

    rc = main([str(input_path)])

    assert rc == 73
    assert called == {"input_file": str(input_path), "to": "all"}


def test_topic_help_surfaces_beginner_and_legacy_guidance(capsys):
    init_rc = main(["help", "init"])
    init_help = capsys.readouterr().out
    runtime_rc = main(["help", "runtime"])
    runtime_help = capsys.readouterr().out
    legacy_rc = main(["help", "legacy"])
    legacy_help = capsys.readouterr().out

    assert init_rc == 0
    assert "Zero-config path:" in init_help
    assert "--owner" in init_help
    assert "--namespace" in init_help
    assert runtime_rc == 0
    assert "cortex connect manus --check" in runtime_help
    assert "cortex serve manus" in runtime_help
    assert legacy_rc == 0
    assert "portable  -> cortex mind ingest / mount" in legacy_help
    assert "cortex --help-all" in legacy_help


def test_portable_remember_build_and_audit_print_compatibility_hints(tmp_path, capsys, monkeypatch):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    store_dir = tmp_path / ".cortex"
    graph_path = tmp_path / "context.json"
    package_json = project_dir / "package.json"

    home_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    _write_graph(graph_path)
    package_json.write_text(
        json.dumps({"name": "cortex-app", "dependencies": {"next": "14.1.0"}}, indent=2),
        encoding="utf-8",
    )

    portable_rc = main(
        [
            "portable",
            str(graph_path),
            "--store-dir",
            str(store_dir),
            "--project",
            str(project_dir),
            "--dry-run",
        ]
    )
    portable_streams = capsys.readouterr()
    init_rc = main(["init", "--store-dir", str(store_dir), "--mind", "marc", "--owner", "marc", "--format", "json"])
    capsys.readouterr()
    remember_rc = main(
        [
            "remember",
            "I prefer concise technical answers.",
            "--store-dir",
            str(store_dir),
            "--project",
            str(project_dir),
            "--dry-run",
        ]
    )
    remember_streams = capsys.readouterr()
    build_rc = main(
        [
            "build",
            "--from",
            "package.json",
            "--store-dir",
            str(store_dir),
            "--project",
            str(project_dir),
        ]
    )
    build_streams = capsys.readouterr()
    audit_rc = main(["audit", "--store-dir", str(store_dir), "--project", str(project_dir)])
    audit_streams = capsys.readouterr()

    assert portable_rc == 0
    assert "cortex mind ingest <mind> --from-detected" in portable_streams.err
    assert init_rc == 0
    assert remember_rc == 0
    assert 'cortex mind remember <mind> "..."' in remember_streams.err
    assert build_rc == 0
    assert "cortex pack" in build_streams.err
    assert audit_rc == 0
    assert "cortex doctor" in audit_streams.err
