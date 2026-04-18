from __future__ import annotations

import hashlib
import json

from cortex.openapi import build_openapi_spec


OPENAPI_SORT_KEYS_SHA256 = "dd23ca4b8b88c27e9c70ac90f16b729f6c8337d1618759100f8f483a32487cff"
OPENAPI_SORT_KEYS_LENGTH = 34438


def test_openapi_golden_is_byte_identical_after_endpoint_builder_split():
    canonical = json.dumps(build_openapi_spec(), sort_keys=True)

    assert len(canonical) == OPENAPI_SORT_KEYS_LENGTH
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == OPENAPI_SORT_KEYS_SHA256
