from __future__ import annotations

import hashlib
import json

from cortex.service.openapi import build_openapi_spec

OPENAPI_SORT_KEYS_SHA256 = "fde61003f18b1e3a9fdbdcbd7d71caa4cc0313218c2abc05bd596b3e0d114212"
OPENAPI_SORT_KEYS_LENGTH = 37982


def test_openapi_golden_is_byte_identical_after_endpoint_builder_split():
    canonical = json.dumps(build_openapi_spec(), sort_keys=True)

    assert len(canonical) == OPENAPI_SORT_KEYS_LENGTH
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == OPENAPI_SORT_KEYS_SHA256
