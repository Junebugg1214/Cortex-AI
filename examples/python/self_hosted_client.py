from __future__ import annotations

from cortex.session import MemorySession


def main() -> None:
    session = MemorySession.from_base_url(
        "http://127.0.0.1:8766",
        api_key="replace-me",
        namespace="team",
        actor="examples/python",
    )

    print("sdk:", session.sdk_info())
    print("health:", session.client.health()["status"])

    session.remember(
        label="Project Atlas",
        node_id="atlas",
        brief="Local-first memory runtime",
        aliases=["atlas"],
        tags=["active_priorities"],
        confidence=0.94,
        message="seed atlas from python session example",
    )

    session.remember(
        label="Python SDK",
        node_id="sdk",
        brief="Programmatic Cortex client",
        tags=["infrastructure"],
        confidence=0.88,
        message="seed sdk from python session example",
    )

    session.link(source_id="atlas", target_id="sdk", relation="depends_on")
    context = session.search_context(query="atlas", limit=5)
    branch = session.branch_for_task("Atlas follow-up")

    print("branch:", branch["branch_name"])
    print(context["context"])


if __name__ == "__main__":
    main()
