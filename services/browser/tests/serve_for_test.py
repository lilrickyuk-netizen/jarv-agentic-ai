"""
Runs JAI's browser service exactly as it runs in production (uvicorn, in its own process and main thread), for the
test only, with one change: pages on this container's loopback address may be opened, so the test can serve its
own page with no network. JAI's real service never loads this file.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the service's own folder, where server.py is

import uvicorn  # noqa: E402

import server  # noqa: E402

PORT = int(sys.argv[1])
_public = server.public_url
server.public_url = lambda url: None if url.startswith("http://127.0.0.1:") else _public(url)
server.PROHIBITED = tuple(d for d in server.PROHIBITED if d != "127.0.0.1")
server.TOKEN = "test-token"

if __name__ == "__main__":
    uvicorn.run(server.app, host="127.0.0.1", port=PORT, log_level="warning")
