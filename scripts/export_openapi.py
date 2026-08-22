from __future__ import annotations

import json
from pathlib import Path

from app.main import create_app


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "packages" / "api-client" / "openapi.json"


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(TARGET)


if __name__ == "__main__":
    main()

