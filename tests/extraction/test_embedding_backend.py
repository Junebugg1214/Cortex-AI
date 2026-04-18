from __future__ import annotations

import pytest

from cortex.extraction import EMBEDDING_BACKEND_DISABLED_MESSAGE, EmbeddingBackend


def test_embedding_backend_constructor_raises_not_implemented():
    with pytest.raises(NotImplementedError) as excinfo:
        EmbeddingBackend()
    assert str(excinfo.value) == EMBEDDING_BACKEND_DISABLED_MESSAGE
