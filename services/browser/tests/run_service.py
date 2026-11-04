"""
Runs JAI's browser service exactly as it runs in production (uvicorn, in its own process and main thread), for the
browser test only, with one change: pages on this container's loopback address may be opened, so the test can
serve its own page with no network. JAI's real service never loads this file, and pytest does not collect it.
"""
import sys
from pathlib import Path


def main(port: int) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the service's folder, where server.py is
    import uvicorn

    import server

    public = server.public_url
    server.public_url = lambda url: None if url.startswith("http://127.0.0.1:") else public(url)
    server.PROHIBITED = tuple(d for d in server.PROHIBITED if d != "127.0.0.1")
    server.TOKEN = "test-token"
    uvicorn.run(server.app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main(int(sys.argv[1]))
