from __future__ import annotations

from cortex.client import CortexClient


def main() -> None:
    client = CortexClient(
        "http://127.0.0.1:8766",
        api_key="replace-me",
        namespace="team",
    )

    print("sdk:", client.sdk_info())
    print("health:", client.health()["status"])

    client.upsert_node(
        node={
            "id": "atlas",
            "label": "Project Atlas",
            "aliases": ["atlas"],
            "tags": ["active_priorities"],
            "confidence": 0.94,
        },
        message="seed atlas from python example",
    )

    results = client.query_search(query="atlas", limit=5)
    print("query count:", results["count"])
    print("top result:", results["results"][0]["node"]["label"])


if __name__ == "__main__":
    main()
