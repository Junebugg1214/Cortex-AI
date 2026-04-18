from __future__ import annotations

from importlib import import_module

from cortex.extraction.prompts import Prompt, available_prompts, load_prompt

_PROMPT_REFERENCE_MODULES = (
    "cortex.extraction.model_backend",
    "cortex.extraction.stages.candidates",
    "cortex.extraction.stages.typing",
    "cortex.extraction.stages.canonicalize",
    "cortex.extraction.stages.relations",
)


def _referenced_prompts() -> set[tuple[str, str]]:
    references: set[tuple[str, str]] = set()
    for module_name in _PROMPT_REFERENCE_MODULES:
        module = import_module(module_name)
        references.update(getattr(module, "PROMPT_REFERENCES", ()))
    return references


def test_all_prompts_referenced_are_loadable() -> None:
    references = _referenced_prompts()

    assert references == {
        ("candidates", "v1"),
        ("typing", "v1"),
        ("canonicalize", "v1"),
        ("relations", "v1"),
    }
    assert references.issubset(set(available_prompts()))
    for name, version in references:
        prompt = load_prompt(name, version)
        assert isinstance(prompt, Prompt)
        assert prompt.name == name
        assert prompt.version == version
        assert prompt.schema_ref
        assert prompt.inputs
        assert prompt.outputs
        assert prompt.test_fixture.startswith("tests/extraction/")
        assert prompt.content
