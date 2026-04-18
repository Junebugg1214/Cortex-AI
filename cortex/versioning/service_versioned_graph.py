from __future__ import annotations

from cortex.service_graph_merge import MemoryGraphMergeServiceMixin
from cortex.service_graph_queries import MemoryGraphQueryServiceMixin


class MemoryVersionedGraphServiceMixin(MemoryGraphMergeServiceMixin, MemoryGraphQueryServiceMixin):
    pass
