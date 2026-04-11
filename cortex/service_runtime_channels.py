from __future__ import annotations

from pathlib import Path
from typing import Any


class MemoryRuntimeChannelMixin:
    def channel_prepare_turn(
        self,
        *,
        message: dict[str, Any],
        target: str | None = None,
        smart: bool = True,
        max_chars: int = 1500,
        project_dir: str = "",
    ) -> dict[str, Any]:
        from cortex.channel_runtime import (
            ChannelContextBridge,
            channel_message_from_dict,
            channel_turn_to_dict,
        )

        channel_message = channel_message_from_dict(message)
        if project_dir and not channel_message.project_dir:
            channel_message.project_dir = str(Path(project_dir).resolve())
        bridge = ChannelContextBridge(self, default_project_dir=Path(project_dir).resolve() if project_dir else None)
        turn = bridge.prepare_turn(
            channel_message,
            target=target,
            smart=smart,
            max_chars=max_chars,
        )
        payload = {"status": "ok", "turn": channel_turn_to_dict(turn)}
        payload["release"] = self.release()
        return payload

    def channel_seed_turn_memory(
        self,
        *,
        turn: dict[str, Any],
        ref: str = "HEAD",
        source: str = "channel.runtime",
        approve: bool = False,
    ) -> dict[str, Any]:
        from cortex.channel_runtime import ChannelContextBridge, channel_turn_from_dict

        bridge = ChannelContextBridge(self)
        payload = bridge.seed_turn_memory(
            channel_turn_from_dict(turn),
            ref=ref,
            source=source,
            approve=approve,
        )
        payload["release"] = self.release()
        return payload


__all__ = ["MemoryRuntimeChannelMixin"]
