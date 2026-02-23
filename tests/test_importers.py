"""Tests for cortex.caas.importers — resume, LinkedIn, GitHub import helpers."""

from __future__ import annotations

import io
import json
import struct
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from cortex.caas.importers import (
    detect_file_type,
    extract_text_from_docx,
    extract_text_from_pdf,
    fetch_github_repo,
    fetch_linkedin_profile,
    parse_linkedin_export,
    parse_resume_text,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_docx(paragraphs: list[str]) -> bytes:
    """Build a minimal DOCX (zip with word/document.xml) in memory."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body_parts = []
    for text in paragraphs:
        body_parts.append(
            f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>'
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{ns}"><w:body>'
        + "".join(body_parts) +
        '</w:body></w:document>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


def _make_linkedin_zip(csvs: dict[str, str]) -> bytes:
    """Build a LinkedIn export zip with the given CSV filenames and content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in csvs.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _make_simple_pdf(text: str) -> bytes:
    """Build a minimal PDF with text in a BT/ET block."""
    content = f"BT\n({text}) Tj\nET"
    stream = content.encode("latin-1")
    # Minimal PDF structure
    pdf = (
        b"%PDF-1.0\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream +
        b"\nendstream\nendobj\n"
        b"%%EOF\n"
    )
    return pdf


# ── PDF Extraction ───────────────────────────────────────────────────

class TestPDFExtraction:
    """Test extract_text_from_pdf()."""

    def test_simple_pdf_text(self):
        pdf = _make_simple_pdf("Hello World")
        result = extract_text_from_pdf(pdf)
        assert "Hello World" in result

    def test_multiple_text_blocks(self):
        content = b"%PDF-1.0\nBT\n(Line One) Tj\nET\nBT\n(Line Two) Tj\nET\n%%EOF"
        result = extract_text_from_pdf(content)
        assert "Line One" in result
        assert "Line Two" in result

    def test_empty_pdf(self):
        pdf = b"%PDF-1.0\n%%EOF"
        result = extract_text_from_pdf(pdf)
        assert result == ""

    def test_non_pdf_bytes(self):
        result = extract_text_from_pdf(b"This is not a PDF")
        # Should not crash; may return empty
        assert isinstance(result, str)


# ── DOCX Extraction ──────────────────────────────────────────────────

class TestDOCXExtraction:
    """Test extract_text_from_docx()."""

    def test_simple_docx(self):
        data = _make_docx(["Hello World"])
        result = extract_text_from_docx(data)
        assert "Hello World" in result

    def test_multi_paragraph(self):
        data = _make_docx(["First paragraph", "Second paragraph"])
        result = extract_text_from_docx(data)
        assert "First paragraph" in result
        assert "Second paragraph" in result

    def test_empty_docx(self):
        data = _make_docx([])
        result = extract_text_from_docx(data)
        assert result == ""

    def test_non_docx_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("not_word.txt", "hello")
        result = extract_text_from_docx(buf.getvalue())
        assert result == ""

    def test_non_zip_bytes(self):
        result = extract_text_from_docx(b"not a zip file at all")
        assert result == ""


# ── Resume Parser ────────────────────────────────────────────────────

class TestResumeParser:
    """Test parse_resume_text()."""

    def test_extracts_nodes_from_resume(self):
        text = (
            "John Smith is a Senior Software Engineer at Google.\n\n"
            "He specializes in Python, Kubernetes, and distributed systems.\n\n"
            "He has 10 years of experience in cloud computing."
        )
        result = parse_resume_text(text)
        assert result["source_type"] == "resume"
        assert len(result["nodes"]) > 0
        # Should find at least some skill or identity nodes
        all_labels = [n["label"].lower() for n in result["nodes"]]
        all_tags = []
        for n in result["nodes"]:
            all_tags.extend(n["tags"])
        assert len(all_tags) > 0

    def test_returns_edges(self):
        text = (
            "Jane Doe works as a Data Scientist at Meta.\n\n"
            "She uses Python and TensorFlow for machine learning projects."
        )
        result = parse_resume_text(text)
        assert result["source_type"] == "resume"
        # Edges are generated by the extractor
        assert isinstance(result["edges"], list)

    def test_empty_text(self):
        result = parse_resume_text("")
        assert result == {"nodes": [], "edges": [], "source_type": "resume"}

    def test_whitespace_only(self):
        result = parse_resume_text("   \n\n  ")
        assert result == {"nodes": [], "edges": [], "source_type": "resume"}


# ── LinkedIn Export ──────────────────────────────────────────────────

class TestLinkedInExport:
    """Test parse_linkedin_export()."""

    def test_full_export(self):
        csvs = {
            "Profile.csv": "First Name,Last Name,Headline,Summary\nJohn,Doe,Engineer,Builds stuff\n",
            "Positions.csv": "Title,Company Name\nSenior Dev,Acme Corp\n",
            "Skills.csv": "Name\nPython\nJavaScript\n",
            "Education.csv": "School Name,Degree Name\nMIT,BS Computer Science\n",
        }
        data = _make_linkedin_zip(csvs)
        result = parse_linkedin_export(data)
        assert result["source_type"] == "linkedin_export"
        labels = [n["label"] for n in result["nodes"]]
        assert "John Doe" in labels
        assert "Engineer" in labels
        assert "Python" in labels
        assert "MIT" in labels
        assert len(result["edges"]) > 0

    def test_profile_csv_only(self):
        csvs = {"Profile.csv": "First Name,Last Name,Headline\nAlice,Smith,Designer\n"}
        data = _make_linkedin_zip(csvs)
        result = parse_linkedin_export(data)
        labels = [n["label"] for n in result["nodes"]]
        assert "Alice Smith" in labels
        assert "Designer" in labels

    def test_positions_create_edges(self):
        csvs = {"Positions.csv": "Title,Company Name\nCTO,StartupX\n"}
        data = _make_linkedin_zip(csvs)
        result = parse_linkedin_export(data)
        rels = [e["relation"] for e in result["edges"]]
        assert "worked_at" in rels

    def test_skills_nodes(self):
        csvs = {"Skills.csv": "Name\nReact\nTypeScript\nDocker\n"}
        data = _make_linkedin_zip(csvs)
        result = parse_linkedin_export(data)
        labels = [n["label"] for n in result["nodes"]]
        assert "React" in labels
        assert "TypeScript" in labels
        tags = [t for n in result["nodes"] for t in n["tags"]]
        assert "technical_expertise" in tags

    def test_education_edges(self):
        csvs = {"Education.csv": "School Name,Degree Name\nStanford,MS AI\n"}
        data = _make_linkedin_zip(csvs)
        result = parse_linkedin_export(data)
        rels = [e["relation"] for e in result["edges"]]
        assert "studied_at" in rels

    def test_missing_csvs(self):
        csvs = {"README.md": "This is not a CSV"}
        data = _make_linkedin_zip(csvs)
        result = parse_linkedin_export(data)
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_bad_zip(self):
        result = parse_linkedin_export(b"not a zip")
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_languages_and_certs(self):
        csvs = {
            "Languages.csv": "Name\nEnglish\nSpanish\n",
            "Certifications.csv": "Name\nAWS Solutions Architect\n",
        }
        data = _make_linkedin_zip(csvs)
        result = parse_linkedin_export(data)
        labels = [n["label"] for n in result["nodes"]]
        assert "English" in labels
        assert "AWS Solutions Architect" in labels


# ── LinkedIn URL ─────────────────────────────────────────────────────

class TestLinkedInURL:
    """Test fetch_linkedin_profile()."""

    def test_invalid_url(self):
        result = fetch_linkedin_profile("https://example.com/notlinkedin")
        assert result["limited"] is True
        assert "error" in result

    @patch("cortex.caas.importers.urllib.request.urlopen")
    def test_valid_url_with_og_tags(self, mock_urlopen):
        html = (
            '<html><head>'
            '<meta property="og:title" content="Jane Doe - Engineer">'
            '<meta property="og:description" content="Software engineer at Big Corp">'
            '</head></html>'
        ).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = html
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_linkedin_profile("https://www.linkedin.com/in/janedoe")
        assert result["source_type"] == "linkedin_url"
        assert result["limited"] is True
        labels = [n["label"] for n in result["nodes"]]
        assert "Jane Doe - Engineer" in labels

    @patch("cortex.caas.importers.urllib.request.urlopen")
    def test_network_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("timeout")
        result = fetch_linkedin_profile("https://linkedin.com/in/someone")
        assert result["limited"] is True
        assert "error" in result


# ── GitHub Import ────────────────────────────────────────────────────

class TestGitHubImport:
    """Test fetch_github_repo()."""

    def test_invalid_url(self):
        result = fetch_github_repo("https://example.com/not-github")
        assert "error" in result
        assert result["nodes"] == []

    @patch("cortex.caas.importers.urllib.request.urlopen")
    def test_full_fetch(self, mock_urlopen):
        repo_json = json.dumps({
            "full_name": "user/my-project",
            "description": "A cool project",
            "language": "Python",
            "topics": ["ai", "ml"],
            "stargazers_count": 42,
            "forks_count": 5,
        }).encode()
        langs_json = json.dumps({"Python": 8000, "JavaScript": 2000}).encode()
        import base64
        readme_json = json.dumps({
            "content": base64.b64encode(b"# My Project\nThis is a README").decode(),
        }).encode()

        responses = [
            _mock_response(repo_json),
            _mock_response(langs_json),
            _mock_response(readme_json),
        ]
        mock_urlopen.side_effect = responses

        result = fetch_github_repo("https://github.com/user/my-project")
        assert result["source_type"] == "github"
        labels = [n["label"] for n in result["nodes"]]
        assert "user/my-project" in labels
        assert "Python" in labels
        assert "JavaScript" in labels
        assert "ai" in labels
        rels = [e["relation"] for e in result["edges"]]
        assert "uses_language" in rels
        assert "tagged_with" in rels

    @patch("cortex.caas.importers.urllib.request.urlopen")
    def test_with_token_sets_header(self, mock_urlopen):
        repo_json = json.dumps({
            "full_name": "org/private-repo",
            "description": "Private",
            "language": "Go",
            "topics": [],
            "stargazers_count": 0,
            "forks_count": 0,
        }).encode()
        langs_json = json.dumps({"Go": 5000}).encode()

        responses = [
            _mock_response(repo_json),
            _mock_response(langs_json),
            # README fetch may raise
            _mock_error_response(),
        ]
        mock_urlopen.side_effect = responses

        result = fetch_github_repo("https://github.com/org/private-repo", token="ghp_abc123")
        assert result["source_type"] == "github"
        # Verify that the request was made with auth header
        calls = mock_urlopen.call_args_list
        first_call_req = calls[0][0][0]
        assert first_call_req.get_header("Authorization") == "token ghp_abc123"

    @patch("cortex.caas.importers.urllib.request.urlopen")
    def test_api_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        result = fetch_github_repo("https://github.com/user/repo")
        assert "error" in result

    @patch("cortex.caas.importers.urllib.request.urlopen")
    def test_repo_node_has_stars_info(self, mock_urlopen):
        repo_json = json.dumps({
            "full_name": "user/stars-repo",
            "description": "Starred project",
            "language": "Rust",
            "topics": [],
            "stargazers_count": 1000,
            "forks_count": 200,
        }).encode()
        langs_json = json.dumps({"Rust": 10000}).encode()

        responses = [
            _mock_response(repo_json),
            _mock_response(langs_json),
            _mock_error_response(),
        ]
        mock_urlopen.side_effect = responses

        result = fetch_github_repo("https://github.com/user/stars-repo")
        repo_node = [n for n in result["nodes"] if n["label"] == "user/stars-repo"][0]
        assert "1000" in repo_node["brief"]
        assert "200" in repo_node["brief"]


# ── File Type Detection ──────────────────────────────────────────────

class TestDetectFileType:
    """Test detect_file_type()."""

    def test_pdf(self):
        assert detect_file_type("resume.pdf", b"%PDF-1.4 ...") == "resume_pdf"

    def test_docx(self):
        data = _make_docx(["Hello"])
        assert detect_file_type("resume.docx", data) == "resume_docx"

    def test_linkedin_zip(self):
        data = _make_linkedin_zip({"Profile.csv": "First Name\nJohn\n"})
        assert detect_file_type("linkedin.zip", data) == "linkedin_export"

    def test_chat_export_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("conversations.json", '[]')
        assert detect_file_type("export.zip", buf.getvalue()) == "chat_export"

    def test_plain_json_file(self):
        assert detect_file_type("data.json", b'{"key": "value"}') == "unknown"

    def test_unknown_bytes(self):
        assert detect_file_type("file.bin", b"\x00\x01\x02") == "unknown"


# ── Mock helpers ─────────────────────────────────────────────────────

def _mock_response(data: bytes) -> MagicMock:
    """Create a mock urllib response for use with urlopen."""
    resp = MagicMock()
    resp.read.return_value = data
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _mock_error_response() -> MagicMock:
    """Create a side_effect that raises URLError."""
    import urllib.error
    return urllib.error.URLError("not found")
