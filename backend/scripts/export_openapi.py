import json
from pathlib import Path

from app.main import app

out = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
print(f"Wrote {out}")
