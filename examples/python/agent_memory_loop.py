from __future__ import annotations

from cortex.session import MemorySession


def call_model(user_message: str, memory_context: str) -> str:
    return f"Model reply for: {user_message}\n\nUsing memory:\n{memory_context}"


def summarize_turn(user_message: str, assistant_reply: str) -> str:
    return f"User asked about '{user_message}'. Assistant replied with '{assistant_reply[:80]}'."


def run_turn(user_message: str) -> None:
    session = MemorySession.from_base_url(
        "http://127.0.0.1:8766",
        api_key="replace-me",
        namespace="team",
        actor="examples/agent-loop",
    )

    search = session.search_context(query=user_message, limit=5)
    assistant_reply = call_model(user_message, search["context"])
    summary = summarize_turn(user_message, assistant_reply)

    session.remember(
        label=f"Conversation: {user_message[:40]}",
        brief=summary,
        tags=["conversation_memory", "agent_runtime"],
        message=f"remember turn: {user_message[:40]}",
    )

    print(assistant_reply)


if __name__ == "__main__":
    run_turn("What do we already know about Project Atlas?")
