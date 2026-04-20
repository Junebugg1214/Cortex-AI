from __future__ import annotations

import hashlib
import json

from cortex.service.openapi import build_openapi_spec

OPENAPI_SORT_KEYS_SHA256 = "3e3ca38cf6be8693fb0078193b57b537dab2929389d3a636f9a79a0d050dd01e"
OPENAPI_SORT_KEYS_LENGTH = 34438


def test_openapi_golden_is_byte_identical_after_endpoint_builder_split():
    canonical = json.dumps(build_openapi_spec(), sort_keys=True)

    assert len(canonical) == OPENAPI_SORT_KEYS_LENGTH
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == OPENAPI_SORT_KEYS_SHA256
