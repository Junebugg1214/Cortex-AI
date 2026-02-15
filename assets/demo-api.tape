# demo-api.tape — "Serve It as an API"
# Run: vhs assets/demo-api.tape (from project root)

Output assets/demo-api.gif
Output assets/demo-api.mp4

Set FontSize 16
Set Width 1200
Set Height 700
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

Type "# Start the CaaS API server"
Enter
Sleep 1s

Type "cortex serve context.json --port 8421 2>/dev/null &"
Enter
Sleep 3s

Type ""
Enter
Sleep 500ms

Type "# Grant an access token to Claude"
Enter
Sleep 1s

Type "cortex grant --create --audience Claude --policy professional 2>&1 | tee /tmp/grant.txt"
Enter
Sleep 4s

# Capture token silently
Hide
Type "TOKEN=$(tail -1 /tmp/grant.txt)"
Enter
Sleep 500ms
Show

Type ""
Enter
Sleep 500ms

Type "# Discover the API (standard UPAI endpoint)"
Enter
Sleep 1s

Type "curl -s localhost:8421/.well-known/upai-configuration | python3 -m json.tool"
Enter
Sleep 5s

Type ""
Enter
Sleep 500ms

Type "# Pull context stats with the bearer token"
Enter
Sleep 1s

Type 'curl -s -H "Authorization: Bearer $TOKEN" localhost:8421/context/stats | python3 -m json.tool'
Enter
Sleep 5s

# Cleanup
Hide
Type "kill %1 2>/dev/null"
Enter
Sleep 500ms
Show

Sleep 2s
