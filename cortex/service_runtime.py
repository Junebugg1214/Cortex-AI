from __future__ import annotations

from cortex.service_runtime_agents import MemoryRuntimeAgentMixin
from cortex.service_runtime_channels import MemoryRuntimeChannelMixin
from cortex.service_runtime_common import _backend_name, _safe_head_ref, _safe_index_status
from cortex.service_runtime_meta import MemoryRuntimeMetaMixin
from cortex.service_runtime_minds import MemoryRuntimeMindMixin
from cortex.service_runtime_packs import MemoryRuntimePackMixin
from cortex.service_runtime_portability import MemoryRuntimePortabilityMixin


class MemoryRuntimeServiceMixin(
    MemoryRuntimeAgentMixin,
    MemoryRuntimeMetaMixin,
    MemoryRuntimePortabilityMixin,
    MemoryRuntimeMindMixin,
    MemoryRuntimePackMixin,
    MemoryRuntimeChannelMixin,
):
    pass


__all__ = ["MemoryRuntimeServiceMixin", "_backend_name", "_safe_head_ref", "_safe_index_status"]
