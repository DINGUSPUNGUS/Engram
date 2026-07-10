"""Export the OpenAPI contract as JSON.

Usage: ``python -m engram_api.export_openapi [output-path]``

The committed schema in packages/api-client is generated from this output; CI
regenerates and fails on drift, so the wire contract cannot change silently.
"""

import json
import sys
from pathlib import Path

from engram_api.main import create_app


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    schema = create_app().openapi()
    output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(f"wrote {output}\n")


if __name__ == "__main__":
    main()
