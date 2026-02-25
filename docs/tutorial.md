# Tutorial: Share Your Identity in 5 Minutes

This tutorial walks you through extracting your identity from a ChatGPT export
and sharing it with another AI platform.

## Prerequisites

- A ChatGPT data export (Settings > Data Controls > Export Data)
- Python 3.10+
- Cortex cloned locally

## Step 1: Extract Your Context

```bash
python3 -m cortex.cli migrate chatgpt-export.zip \
    --to all \
    --output ./my-context \
    --schema v5 \
    --discover-edges \
    --verbose
```

This creates:
- `my-context/context.json` — your full identity graph
- `my-context/claude_preferences.txt` — Claude-ready format
- `my-context/notion_page.md` — Notion-ready format
- Other platform exports

## Step 2: Create Your Identity

```bash
python3 -m cortex.cli identity --init --name "Your Name"
```

This generates a DID (Decentralized Identifier) and stores your keys in
`.cortex/`.

## Step 3: Start the Server

```bash
python3 -m cortex.cli serve my-context/context.json --storage sqlite
```

Output:
```
CaaS API: http://127.0.0.1:8421
Identity: did:key:z6MkqR...
Graph: 47 nodes, 23 edges
Storage: sqlite (.cortex/cortex.db)
Dashboard password: a1b2c3d4e5f6...
```

## Step 3b: Use the Web UI (Alternative)

Instead of the dashboard, you can use the consumer web app for a friendlier experience:

```bash
python3 -m cortex.cli serve my-context/context.json --storage sqlite --enable-webapp
```

Open `http://localhost:8421/app` in your browser:

- **Upload** — Drag-and-drop files, import from GitHub/LinkedIn URLs
- **My Memory** — Interactive graph visualization with search and filters
- **Share** — Export to any platform with privacy level selection
- **Profile** — Create and manage public profiles

## Step 4: Explore Your Graph

Open `http://localhost:8421/dashboard` and log in with the displayed password.

- **Overview** shows your identity stats
- **Graph Explorer** lets you visualize and filter your identity
- Try switching the disclosure policy dropdown to see how `professional` vs
  `minimal` changes what's visible

## Step 5: Create a Grant

In the dashboard, go to **Grants** and fill out:
- **Audience**: `claude.ai`
- **Policy**: `professional`
- **Scopes**: `context:read`, `identity:read`
- **TTL**: 24 hours

Click **Create Grant** and copy the token.

Or via CLI:
```bash
python3 -m cortex.cli grant --create \
    --audience "claude.ai" \
    --policy professional \
    --ttl 24
```

## Step 6: Verify It Works

Test the API with the grant token:

```bash
curl -H "Authorization: Bearer <your-token>" \
     http://127.0.0.1:8421/context | python3 -m json.tool
```

You should see your identity graph filtered through the `professional` policy.

## Step 7: Import Back

If you exported to Notion format, you can pull it back:

```bash
python3 -m cortex.cli pull my-context/notion_page.md --from notion -o roundtrip.json
```

This creates a new graph from the Notion export, verifying the round-trip.

## Step 8: Create a Public Profile

Share your professional identity with a public URL:

1. Start the server with `--enable-webapp`:
   ```bash
   python3 -m cortex.cli serve my-context/context.json --storage sqlite --enable-webapp
   ```

2. Open `http://localhost:8421/app` and navigate to the **Profile** page

3. Create a profile:
   - Choose a handle (e.g., `yourname`)
   - Select a disclosure policy (`professional` or `technical`)
   - Add a brief bio

4. Share it:
   - Your public profile is available at `http://localhost:8421/p/yourname`
   - Click **Generate QR Code** to create a scannable code for the URL
   - Anyone visiting the URL sees your filtered identity — no authentication required

5. (Optional) Register a webhook to track views:
   ```bash
   curl -X POST http://localhost:8421/webhooks \
       -H "Authorization: Bearer <token>" \
       -H "Content-Type: application/json" \
       -d '{"url": "https://your-webhook.example.com", "events": ["profile.viewed"]}'
   ```

## Next Steps

- Set up periodic sync with `cortex sync-schedule`
- Monitor for new exports with `cortex watch`
- Add webhooks for real-time notifications
- Explore version history with `cortex log`
