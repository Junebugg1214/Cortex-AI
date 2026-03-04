#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"

make_slide() {
  local out="$1"
  local title="$2"
  local subtitle="$3"
  python3 - "$out" "$title" "$subtitle" <<'PY'
from PIL import Image, ImageDraw, ImageFont
import sys

out, title, subtitle = sys.argv[1], sys.argv[2], sys.argv[3]
w, h = 1280, 720
img = Image.new("RGB", (w, h), "#0f172a")
d = ImageDraw.Draw(img)
d.rounded_rectangle((60, 80, 1220, 640), radius=22, fill="#1e293b", outline="#334155", width=3)

try:
    title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 62)
    subtitle_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 34)
except Exception:
    title_font = ImageFont.load_default()
    subtitle_font = ImageFont.load_default()

tw = d.textlength(title, font=title_font)
sw = d.textlength(subtitle, font=subtitle_font)
d.text(((w - tw) / 2, 250), title, font=title_font, fill="#ffffff")
d.text(((w - sw) / 2, 348), subtitle, font=subtitle_font, fill="#cbd5e1")
img.save(out)
PY
}

# --- Brand / product video slides (45s) ---
make_slide assets/video/slide-01-intro.png "Your AI ID belongs to you" "Portable memory across AI assistants"
make_slide assets/video/slide-02-feature.png "Connector-first continuity" "Sync memory across OpenAI, Claude, Gemini, Grok, and more"
make_slide assets/video/slide-03-feature.png "BYOS + Self-Host only" "Bring your own storage with E2E passphrase or run your own server"
make_slide assets/video/slide-04-outro.png "Share only what you choose" "Policy-based disclosure: full, professional, technical, minimal"

ffmpeg -y \
  -loop 1 -t 11.25 -i assets/video/slide-01-intro.png \
  -loop 1 -t 11.25 -i assets/video/slide-02-feature.png \
  -loop 1 -t 11.25 -i assets/video/slide-03-feature.png \
  -loop 1 -t 11.25 -i assets/video/slide-04-outro.png \
  -filter_complex "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0,fps=30,format=yuv420p" \
  -c:v libx264 -pix_fmt yuv420p -movflags +faststart assets/cortexai_x_45s.mp4

# --- Webapp flow video slides (45s) ---
make_slide assets/video/webapp-01-intro.png "Choose storage" "Start with BYOS cloud or Self-Host"
make_slide assets/video/webapp-02-upload.png "Connect assistants first" "Create connectors and enable auto-sync"
make_slide assets/video/webapp-03-memory.png "Add data manually (optional)" "Use exports/files when connector sync is not enough"
make_slide assets/video/webapp-04-share.png "Review and share your AI ID" "Preview what each policy exposes before sharing"
make_slide assets/video/webapp-05-outro.png "Simple consumer flow" "Connect, review, and share with clear cues"

ffmpeg -y \
  -loop 1 -t 9 -i assets/video/webapp-01-intro.png \
  -loop 1 -t 9 -i assets/video/webapp-02-upload.png \
  -loop 1 -t 9 -i assets/video/webapp-03-memory.png \
  -loop 1 -t 9 -i assets/video/webapp-04-share.png \
  -loop 1 -t 9 -i assets/video/webapp-05-outro.png \
  -filter_complex "[0:v][1:v][2:v][3:v][4:v]concat=n=5:v=1:a=0,fps=30,format=yuv420p" \
  -c:v libx264 -pix_fmt yuv420p -movflags +faststart assets/cortexai_webapp_x_45s.mp4

# --- Demo slides (replace legacy terminal recordings) ---
make_slide assets/video/demo-own.png "Own your AI memory" "Portable identity graph you control"
make_slide assets/video/demo-share.png "Share by policy" "full / professional / technical / minimal"
make_slide assets/video/demo-api.png "Use as an API" "Issue keys and serve memory to assistants"

ffmpeg -y -loop 1 -t 18 -i assets/video/demo-own.png -vf "fps=30,format=yuv420p" -c:v libx264 -pix_fmt yuv420p -movflags +faststart assets/demo-own.mp4
ffmpeg -y -loop 1 -t 18 -i assets/video/demo-share.png -vf "fps=30,format=yuv420p" -c:v libx264 -pix_fmt yuv420p -movflags +faststart assets/demo-share.mp4
ffmpeg -y -loop 1 -t 22 -i assets/video/demo-api.png -vf "fps=30,format=yuv420p" -c:v libx264 -pix_fmt yuv420p -movflags +faststart assets/demo-api.mp4

# MP4 -> GIF (palette method)
ffmpeg -y -i assets/demo-own.mp4 -vf "fps=12,scale=1200:-1:flags=lanczos,palettegen" -frames:v 1 -update 1 /tmp/demo-own-palette.png
ffmpeg -y -i assets/demo-own.mp4 -i /tmp/demo-own-palette.png -lavfi "fps=12,scale=1200:-1:flags=lanczos[x];[x][1:v]paletteuse" assets/demo-own.gif

ffmpeg -y -i assets/demo-share.mp4 -vf "fps=12,scale=1200:-1:flags=lanczos,palettegen" -frames:v 1 -update 1 /tmp/demo-share-palette.png
ffmpeg -y -i assets/demo-share.mp4 -i /tmp/demo-share-palette.png -lavfi "fps=12,scale=1200:-1:flags=lanczos[x];[x][1:v]paletteuse" assets/demo-share.gif

ffmpeg -y -i assets/demo-api.mp4 -vf "fps=12,scale=1200:-1:flags=lanczos,palettegen" -frames:v 1 -update 1 /tmp/demo-api-palette.png
ffmpeg -y -i assets/demo-api.mp4 -i /tmp/demo-api-palette.png -lavfi "fps=12,scale=1200:-1:flags=lanczos[x];[x][1:v]paletteuse" assets/demo-api.gif

echo "Video regeneration complete."
