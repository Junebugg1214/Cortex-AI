# demo-own.tape — "Own Your Memory"
# Run: vhs assets/demo-own.tape (from project root)

Output assets/demo-own.gif
Output assets/demo-own.mp4

Set FontSize 18
Set Width 1200
Set Height 600
Set Theme "Catppuccin Mocha"
Set TypingSpeed 30ms
Set Padding 20

# --- Hidden setup ---
Hide
Type "DEMO=$(mktemp -d) && cp assets/demo-data/demo-export.zip $DEMO/ && cp assets/demo-data/context.json $DEMO/ && cd $DEMO"
Enter
Sleep 1s
Show

# --- Demo ---
Sleep 500ms

Type "# Extract your AI memory from a ChatGPT export"
Enter
Sleep 1s

Type "cortex extract demo-export.zip -o context.json --stats"
Enter
Sleep 4s

Type ""
Enter
Sleep 500ms

Type "# What does your AI know about you?"
Enter
Sleep 1s

Type "cortex stats context.json"
Enter
Sleep 5s

Type ""
Enter
Sleep 500ms

Type "# Query your strongest knowledge areas"
Enter
Sleep 1s

Type "cortex query context.json --strongest 5"
Enter
Sleep 4s

Sleep 2s
