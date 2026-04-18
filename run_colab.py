"""Colab entry point.

1. Generate a random Bearer token and print it.
2. Download cloudflared if not present.
3. Launch `cloudflared tunnel --url http://localhost:8000` as a subprocess,
   scrape its output for the *.trycloudflare.com URL, and print it.
4. Run uvicorn serving app.main:app.

If cloudflared exits unexpectedly, this script exits non-zero.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from app import config

CLOUDFLARED_URLS = {
    "Linux-x86_64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    "Linux-aarch64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
    "Darwin-x86_64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
    "Darwin-arm64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz",
}

BIN_DIR = Path("/content/bin") if Path("/content").exists() else Path.cwd() / "bin"


def ensure_cloudflared() -> Path:
    existing = shutil.which("cloudflared")
    if existing:
        return Path(existing)

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    target = BIN_DIR / "cloudflared"
    if target.exists():
        return target

    key = f"{platform.system()}-{platform.machine()}"
    url = CLOUDFLARED_URLS.get(key)
    if not url:
        raise RuntimeError(f"no cloudflared download configured for {key}")

    print(f"[run_colab] downloading cloudflared for {key} ...", flush=True)
    urllib.request.urlretrieve(url, target)
    target.chmod(0o755)
    return target


TUNNEL_URL_RE = re.compile(r"https://[A-Za-z0-9\-]+\.trycloudflare\.com")


def start_tunnel(bin_path: Path, port: int) -> tuple[subprocess.Popen, str]:
    proc = subprocess.Popen(
        [str(bin_path), "tunnel", "--url", f"http://localhost:{port}", "--no-autoupdate"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    found_url: list[str] = []

    def _reader() -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            sys.stdout.write(f"[cloudflared] {line}")
            sys.stdout.flush()
            if not found_url:
                m = TUNNEL_URL_RE.search(line)
                if m:
                    found_url.append(m.group(0))

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    deadline = time.time() + 30
    while time.time() < deadline and not found_url:
        if proc.poll() is not None:
            raise RuntimeError("cloudflared exited before publishing a URL")
        time.sleep(0.2)
    if not found_url:
        proc.terminate()
        raise RuntimeError("timed out waiting for cloudflared URL")
    return proc, found_url[0]


def main() -> int:
    port = int(os.environ.get("FLUX_PORT", "8000"))
    token = os.environ.get("FLUX_TOKEN") or config.generate_token()
    os.environ["FLUX_TOKEN"] = token

    bin_path = ensure_cloudflared()
    tunnel_proc, public_url = start_tunnel(bin_path, port)

    print("=" * 70, flush=True)
    print(f"FLUX Image Generator is publishing on: {public_url}", flush=True)
    print(f"Bearer token:                          {token}", flush=True)
    print("=" * 70, flush=True)

    import uvicorn

    def _handle_sig(_signum, _frame):
        tunnel_proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    try:
        uvicorn.run("app.main:app", host="0.0.0.0", port=port)
    finally:
        if tunnel_proc.poll() is None:
            tunnel_proc.terminate()
            try:
                tunnel_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel_proc.kill()

    if tunnel_proc.returncode not in (0, -signal.SIGTERM):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
