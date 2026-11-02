"""Check the Meta Model API connection."""
import logging
import sys
from typing import Any

import openai

from muse_client import DEFAULT_MODEL, create_client

logger: logging.Logger = logging.getLogger(__name__)


def run_check() -> int:
    """List models, make one responses call. Returns exit code."""
    try:
        client: openai.OpenAI = create_client()
    except RuntimeError as exc:
        print(f"connection check failed: {exc}", file=sys.stderr)
        logger.error("missing key: %s", exc)
        return 2
    try:
        models: Any = client.models.list()
        names: list[str] = []
        try:
            for item in getattr(models, "data", []):
                names.append(str(getattr(item, "id", item)))
        except Exception:
            names = [str(models)]
        logger.info("models: %s", ", ".join(names))
        resp: Any = client.responses.create(model=DEFAULT_MODEL, input="Reply with exactly: connected", max_output_tokens=200)
        logger.info("reply: %s", str(resp.output_text))
    except openai.AuthenticationError as exc:
        print(f"connection check failed: authentication error: {exc}", file=sys.stderr)
        logger.error("auth error: %s", exc)
        return 1
    except openai.APIStatusError as exc:
        print(f"connection check failed: status error: {exc}", file=sys.stderr)
        logger.error("status error: %s", exc)
        return 1
    except openai.APIConnectionError as exc:
        print(f"connection check failed: connection error: {exc}", file=sys.stderr)
        logger.error("connection error: %s", exc)
        return 1
    return 0


def main() -> None:
    """CLI entrypoint."""
    logging.basicConfig(level=logging.INFO)
    sys.exit(run_check())


if __name__ == "__main__":
    main()
