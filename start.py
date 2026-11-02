import sys

if sys.version_info < (3, 10):
    sys.stdout.write("Blackout needs Python 3.10 or newer.\n")
    raise SystemExit(1)

import argparse
import importlib.util
import socket
import threading
import time
import urllib.request
import webbrowser


def _missing_modules() -> list[str]:
    missing: list[str] = []
    for name in ("fastapi", "uvicorn", "openai", "websockets", "httpx"):
        if importlib.util.find_spec(name) is None:
            missing.append(name)
    return missing


def _port_free(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _choose_port(requested: int | None) -> int:
    if requested is not None and _port_free(requested):
        return requested
    for port in range(8000, 8011):
        if _port_free(port):
            return port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _open_browser(port: int) -> None:
    deadline: float = time.monotonic() + 15.0
    url: str = f"http://127.0.0.1:{port}/api/status"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(f"http://127.0.0.1:{port}/")
                    return
        except Exception:
            pass
        time.sleep(0.3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if _missing_modules():
        sys.stdout.write("Missing packages. Run: pip install -r requirements.txt\n")
        return 1
    port: int = _choose_port(args.port)
    if not args.no_browser:
        thread = threading.Thread(target=_open_browser, args=(port,), daemon=True)
        thread.start()
    sys.stdout.write(f"Blackout is running at http://127.0.0.1:{port} - press Ctrl+C to stop.\n")
    sys.stdout.flush()
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=port, access_log=False, log_level="warning", proxy_headers=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
