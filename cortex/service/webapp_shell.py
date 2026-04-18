"""Static Cortex UI shell and session constants."""

from cortex.webapp_shell_body import UI_BODY
from cortex.webapp_shell_css import UI_CSS
from cortex.webapp_shell_js import UI_JS

UI_SESSION_HEADER = "X-Cortex-UI-Session"
UI_SESSION_PLACEHOLDER = "__CORTEX_UI_SESSION_TOKEN__"


UI_HTML = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cortex UI</title>
  <style>
{UI_CSS}
  </style>
</head>
<body>
{UI_BODY}

  <script>
{UI_JS}
  </script>
</body>
</html>
"""
