import json
from typing import Any


class KeyMeshLogger:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def log(self, event: str, meta: dict[str, Any]) -> None:
        if not self.enabled:
            return

        print(json.dumps({"event": event, "meta": meta}))
    