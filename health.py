"""Report subprocess health without making a network request."""

import json

if __name__ == "__main__":
    print(json.dumps({"ok": True, "status": "healthy", "extension_id": "flowsteward.discord"}))
