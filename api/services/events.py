
import json
import time
from typing import AsyncGenerator
from api.redis_client import get_redis


async def stream_events(submission_id: str) -> AsyncGenerator[str, None]:
    """Stream live and historical events from Redis for a given submission."""
    r = await get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(f"repair_events:{submission_id}")

    # Replay events already stored so late-joining clients don't miss history
    history = await r.lrange(f"repair_history:{submission_id}", 0, -1)
    for event_json in history:
        yield f"data: {event_json}\n\n"

    _TERMINAL_TYPES = {"repair_success", "repair_failed", "error"}

    try:
        last_heartbeat = time.time()
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg:
                data = msg["data"]
                yield f"data: {data}\n\n"
                last_heartbeat = time.time()

                # Terminate cleanly by checking the structured type field
                try:
                    event_type = json.loads(data).get("type", "")
                    if event_type in _TERMINAL_TYPES:
                        break
                except (json.JSONDecodeError, AttributeError):
                    pass

            # SSE keep-alive to prevent proxy timeouts
            if time.time() - last_heartbeat > 15:
                yield ": ping\n\n"
                last_heartbeat = time.time()
    finally:
        await pubsub.unsubscribe(f"repair_events:{submission_id}")
        await pubsub.close()
