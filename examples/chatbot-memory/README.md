# Chatbot Memory Example

End-to-end demonstration of the Cortex pipeline:

1. **Extract** context from a chat export
2. **Load** into a knowledge graph
3. **Query** the graph for relevant information

## Run

```bash
python examples/chatbot-memory/main.py
```

## What it does

- Creates a sample chat export with user preferences and background
- Extracts nodes and edges using the Cortex extractor
- Loads the result into a `CortexGraph`
- Demonstrates search and stats queries
