"""Tests for cortex.completion — shell completion script generation."""

import pytest
from cortex.cli import build_parser
from cortex.completion import (
    GENERATORS,
    _get_flags,
    _get_subcommands,
    generate_bash,
    generate_completion,
    generate_fish,
    generate_zsh,
)


@pytest.fixture
def parser():
    return build_parser()


class TestGetSubcommands:
    def test_returns_sorted_list(self, parser):
        subs = _get_subcommands(parser)
        assert isinstance(subs, list)
        assert len(subs) > 10  # we have 30+ subcommands
        assert subs == sorted(subs)

    def test_known_subcommands_present(self, parser):
        subs = _get_subcommands(parser)
        for expected in ("serve", "query", "migrate", "extract", "import",
                         "identity", "grant", "completion"):
            assert expected in subs, f"Missing subcommand: {expected}"


class TestGetFlags:
    def test_global_flags(self, parser):
        flags = _get_flags(parser)
        assert "-h" in flags or "--help" in flags

    def test_serve_flags(self, parser):
        flags = _get_flags(parser, "serve")
        assert "--port" in flags or "-p" in flags
        assert "--enable-sse" in flags
        assert "--enable-metrics" in flags

    def test_query_flags(self, parser):
        flags = _get_flags(parser, "query")
        assert "--node" in flags
        assert "--neighbors" in flags

    def test_unknown_subcommand_returns_global(self, parser):
        flags = _get_flags(parser, "nonexistent-subcommand-xyz")
        # Falls back to global parser flags
        assert isinstance(flags, list)


class TestBashCompletion:
    def test_generates_script(self, parser):
        script = generate_bash(parser)
        assert "_cortex_completion" in script
        assert "complete -F _cortex_completion cortex" in script
        assert "serve" in script
        assert "query" in script

    def test_contains_subcommand_flags(self, parser):
        script = generate_bash(parser)
        assert "--port" in script
        assert "--enable-sse" in script


class TestZshCompletion:
    def test_generates_script(self, parser):
        script = generate_zsh(parser)
        assert "#compdef cortex" in script
        assert "_cortex" in script
        assert "serve" in script

    def test_contains_arguments(self, parser):
        script = generate_zsh(parser)
        assert "_arguments" in script


class TestFishCompletion:
    def test_generates_script(self, parser):
        script = generate_fish(parser)
        assert "complete -c cortex" in script
        assert "__fish_use_subcommand" in script
        assert "serve" in script

    def test_contains_long_flags(self, parser):
        script = generate_fish(parser)
        assert "__fish_seen_subcommand_from serve" in script


class TestGenerateCompletion:
    def test_bash(self, parser):
        script = generate_completion(parser, "bash")
        assert "complete -F _cortex_completion cortex" in script

    def test_zsh(self, parser):
        script = generate_completion(parser, "zsh")
        assert "#compdef cortex" in script

    def test_fish(self, parser):
        script = generate_completion(parser, "fish")
        assert "complete -c cortex" in script

    def test_unsupported_shell_raises(self, parser):
        with pytest.raises(ValueError, match="Unsupported shell"):
            generate_completion(parser, "powershell")

    def test_generators_dict_matches(self):
        assert set(GENERATORS.keys()) == {"bash", "zsh", "fish"}


class TestCLIIntegration:
    def test_completion_subcommand_exists(self):
        from cortex.cli import main
        # Should produce output (the completion script), not error
        # We just check it doesn't crash
        result = main(["completion", "--shell", "bash"])
        assert result == 0

    def test_completion_zsh(self):
        from cortex.cli import main
        result = main(["completion", "--shell", "zsh"])
        assert result == 0

    def test_completion_fish(self):
        from cortex.cli import main
        result = main(["completion", "--shell", "fish"])
        assert result == 0
