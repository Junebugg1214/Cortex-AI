"""Tests for upload extraction across common assistant export formats."""

from cortex.caas.server import CaaSHandler
from cortex.caas.importers import parse_linkedin_export, parse_resume_text
from cortex.graph import CortexGraph


def _extract(parsed):
    handler = object.__new__(CaaSHandler)
    CaaSHandler.graph = CortexGraph()
    return CaaSHandler._extract_from_upload(handler, parsed)


def test_extract_openai_mapping_list():
    parsed = [
        {
            "title": "OpenAI export",
            "mapping": {
                "a": {
                    "message": {
                        "content": {
                            "content_type": "text",
                            "parts": ["I manage product strategy for AI tools."],
                        }
                    }
                },
                "b": {
                    "message": {
                        "content": {
                            "content_type": "text",
                            "parts": ["I prefer Python and SQL for analytics."],
                        }
                    }
                },
            },
        }
    ]
    result = _extract(parsed)
    assert result["nodes_created"] >= 1


def test_extract_claude_chat_messages_shape():
    parsed = {
        "chat_messages": [
            {"sender": "human", "text": "I live in Florida and run a startup."},
            {"sender": "assistant", "text": "You focus on SaaS growth and GTM."},
        ]
    }
    result = _extract(parsed)
    assert result["nodes_created"] >= 1


def test_extract_gemini_turns_shape():
    parsed = {
        "turns": [
            {"role": "user", "content": {"parts": ["I work at Google on cloud data platforms."]}},
            {"role": "model", "content": {"parts": ["You are interested in distributed systems."]}},
        ]
    }
    result = _extract(parsed)
    assert result["nodes_created"] >= 1


def test_resume_parser_extracts_nodes():
    text = "Jane Doe is a Senior Engineer at Acme Corp with expertise in Python and ML."
    result = parse_resume_text(text)
    assert result["source_type"] == "resume"
    assert len(result["nodes"]) >= 1


def test_linkedin_parser_extracts_nodes():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "Profile.csv",
            "First Name,Last Name,Headline,Summary\n"
            "John,Smith,Senior Engineer,Building AI products\n",
        )
        zf.writestr(
            "Skills.csv",
            "Name\nPython\n",
        )
    result = parse_linkedin_export(buf.getvalue())
    assert result["source_type"] == "linkedin_export"
    assert len(result["nodes"]) >= 1
