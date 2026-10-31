"""Explicit live connectivity check; unit tests never call the paid API."""

import json

from app.core.independence import BlindRequest, Message
from app.llm.meta import MetaAPIError, MetaClient, MetaSettings


def main() -> int:
    try:
        settings = MetaSettings.from_dotenv()
        request = BlindRequest((Message("user", "Reply with only the single word: ready"),))
        completion = MetaClient(settings).complete(request, max_completion_tokens=512, reasoning_effort="minimal")
        print(json.dumps({"status": "CONNECTED", "model": completion.model,
                          "ready": completion.text.strip().lower() == "ready", "usage": completion.usage}))
        return 0
    except (ValueError, MetaAPIError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
