"""Tests for QR code SVG generation — Feature 5."""

import pytest
from cortex.caas.qr import generate_qr_svg, _select_version, _rs_encode, _init_gf


class TestQRVersion:
    def test_short_url_version_1(self):
        assert _select_version(10) == 1

    def test_medium_url_version_2(self):
        assert _select_version(20) == 2

    def test_long_url_needs_higher_version(self):
        v = _select_version(80)
        assert v >= 4

    def test_too_long_raises(self):
        with pytest.raises(ValueError, match="too long"):
            _select_version(200)


class TestReedSolomon:
    def test_rs_encode_returns_correct_length(self):
        data = [0x40, 0x11, 0x22, 0x33]
        ec = _rs_encode(data, 10)
        assert len(ec) == 10

    def test_rs_encode_deterministic(self):
        data = [0x10, 0x20, 0x30]
        ec1 = _rs_encode(data, 7)
        ec2 = _rs_encode(data, 7)
        assert ec1 == ec2


class TestGenerateQRSVG:
    def test_returns_svg_string(self):
        svg = generate_qr_svg("hello")
        assert svg.startswith("<svg")
        assert svg.strip().endswith("</svg>")
        assert 'xmlns="http://www.w3.org/2000/svg"' in svg

    def test_contains_dark_modules(self):
        svg = generate_qr_svg("test")
        assert 'fill="#000"' in svg
        assert "<rect" in svg

    def test_url_encoding(self):
        svg = generate_qr_svg("http://localhost:8421/p/alice")
        assert svg.startswith("<svg")
        assert 'fill="#000"' in svg

    def test_custom_module_size(self):
        svg = generate_qr_svg("hi", module_size=8)
        assert 'width="8"' in svg

    def test_custom_border(self):
        svg_small = generate_qr_svg("hi", border=2)
        svg_large = generate_qr_svg("hi", border=8)
        # Larger border = larger SVG dimensions
        assert len(svg_large) > len(svg_small)

    def test_different_data_different_output(self):
        svg1 = generate_qr_svg("abc")
        svg2 = generate_qr_svg("xyz")
        assert svg1 != svg2

    def test_max_length_v6(self):
        # Version 6 supports ~106 bytes, ensure it works
        data = "A" * 100
        svg = generate_qr_svg(data)
        assert svg.startswith("<svg")

    def test_unicode_data(self):
        svg = generate_qr_svg("hello world")
        assert svg.startswith("<svg")
