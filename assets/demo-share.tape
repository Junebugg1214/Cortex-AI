# demo-share.tape — "Share How You Want"
# Run: vhs assets/demo-share.tape (from project root)

Output assets/demo-share.gif
Output assets/demo-share.mp4

Set FontSize 18
Set Width 1200
Set Height 600
Set Theme "Catppuccin Mocha"
Set TypingSpeed 30ms
Set Padding 20

# --- Hidden setup ---
Hide
Type "DEMO=$(mktemp -d) && cp assets/demo-data/context.json $DEMO/ && cd $DEMO"
Enter
Sleep 500ms
Type "cortex identity --init --name 'Demo User' --store-dir .cortex 2>/dev/null"
Enter
Sleep 1s
Show

# --- Demo ---
Sleep 500ms

Type "# Sync to Claude with full professional context"
Enter
Sleep 1s

Type "cortex sync context.json --to claude --policy professional -o ./pro"
Enter
Sleep 3s

Type ""
Enter
Sleep 500ms

Type "# Same graph, minimal disclosure — you control what each platform sees"
Enter
Sleep 1s

Type "cortex sync context.json --to claude --policy minimal -o ./min"
Enter
Sleep 3s

Type ""
Enter
Sleep 500ms

Type "# Compare what each policy reveals"
Enter
Sleep 1s

Type "echo '--- professional ---' && wc -c pro/* && echo '--- minimal ---' && wc -c min/*"
Enter
Sleep 4s

Sleep 2s
