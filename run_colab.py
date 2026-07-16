"""Colab entry point.

1. Generate a random Bearer token and print it.
2. Download cloudflared if not present.
3. Open a Cloudflare tunnel to http://localhost:8000, in one of two modes:
     - Named tunnel (STABLE URL): when a token is found (CLOUDFLARE_TUNNEL_TOKEN
       env var or a Colab Secret of the same name), run `cloudflared tunnel run
       --token ...`. The public hostname is fixed (TUNNEL_HOSTNAME, default
       flux.codecrab.dev) and survives restarts. This is the one-click path:
       store the token once as a Colab Secret and a bare `!python run_colab.py`
       publishes on the stable URL.
     - Quick tunnel (zero-config, EPHEMERAL URL): otherwise run
       `cloudflared tunnel --url ...` and scrape the random *.trycloudflare.com
       URL from its output. The URL changes on every restart.
4. Run uvicorn serving app.main:app.
5. Supervise the tunnel: cloudflared (especially TryCloudflare quick tunnels)
   can get torn down / crash mid-session while uvicorn keeps running, silently
   killing public access. A background supervisor watches the cloudflared
   process AND actively probes the public URL's /healthz through Cloudflare; on
   repeated failure it restarts the tunnel (same mode) and reprints the URL.

The supervisor keeps the service reachable for the life of the Colab session.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import signal
import socket
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
}

BIN_DIR = Path("/content/bin") if Path("/content").exists() else Path.cwd() / "bin"

# Baked-in default so a bare `!python run_colab.py` publishes on a stable URL
# without the user exporting anything. Override with the TUNNEL_HOSTNAME env var.
DEFAULT_TUNNEL_HOSTNAME = "flux.codecrab.dev"


def resolve_cf_token() -> "str | None":
    """Find the Cloudflare named-tunnel token for one-click Colab runs.

    Order: the CLOUDFLARE_TUNNEL_TOKEN env var, then a Colab Secret of the same
    name (the 🔑 panel). Returning None means "no token" -> fall back to the
    zero-config quick tunnel. Storing the token as a Colab Secret keeps it out
    of the notebook and out of git while still making `!python run_colab.py`
    a single step.
    """
    tok = os.environ.get("CLOUDFLARE_TUNNEL_TOKEN")
    if tok and tok.strip():
        return tok.strip()
    try:
        from google.colab import userdata  # type: ignore[import-not-found]

        val = userdata.get("CLOUDFLARE_TUNNEL_TOKEN")
        return val.strip() if val and val.strip() else None
    except Exception:
        # Not on Colab, secret not set, or notebook access not granted.
        return None


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


def start_named_tunnel(bin_path: Path, token: str, hostname: str) -> tuple[subprocess.Popen, str]:
    """Run a remotely-managed (token) named tunnel.

    Ingress (public hostname -> http://localhost:PORT) is configured in the
    Cloudflare Zero Trust dashboard, not here, so we don't pass --url; the
    public URL is the fixed `hostname` and does not change across restarts.
    We wait for the first "Registered tunnel connection" line as a readiness
    signal, then hand off to the supervisor's active /healthz probing.
    """
    # Flag ordering matters: `cloudflared tunnel [tunnel opts] run [run opts]`.
    # --no-autoupdate is a *tunnel*-level option and must precede `run`; only
    # --token belongs to the `run` subcommand. Putting --no-autoupdate after
    # `run` makes cloudflared exit with "flag provided but not defined".
    proc = subprocess.Popen(
        [str(bin_path), "tunnel", "--no-autoupdate", "run", "--token", token],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    registered = threading.Event()

    def _reader() -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            sys.stdout.write(f"[cloudflared] {line}")
            sys.stdout.flush()
            if not registered.is_set() and "Registered tunnel connection" in line:
                registered.set()

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    deadline = time.time() + 30
    while time.time() < deadline and not registered.is_set():
        if proc.poll() is not None:
            raise RuntimeError("cloudflared exited before registering the tunnel")
        time.sleep(0.2)
    # Not fatal if we never saw the marker within 30s; the supervisor's /healthz
    # probe is the real readiness gate.
    return proc, f"https://{hostname}"


def probe_public(public_url: str, timeout: float = 10.0) -> bool:
    """Return True iff the public URL serves our app through Cloudflare.

    Hits the unauthenticated /healthz. A dead/torn-down tunnel returns a
    Cloudflare error page (5xx/1033), which urllib raises on -> False. Only a
    real 200 from our own app counts as healthy.
    """
    req = urllib.request.Request(f"{public_url}/healthz", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def supervise_tunnel(
    spawn,
    holder: dict,
    stop_event: threading.Event,
    *,
    interval: float = 15.0,
    grace: float = 20.0,
    threshold: int = 3,
) -> None:
    """Keep the tunnel alive for the whole session (both quick and named modes).

    `spawn` is a zero-arg callable returning `(proc, url)` for a fresh tunnel of
    the same mode. holder["proc"]/["url"] hold the current cloudflared process
    and public URL; this thread updates them in place on restart so the signal
    handler and shutdown path always see the live process.

    A restart triggers when either the cloudflared process has exited, or the
    public /healthz fails `threshold` consecutive probes. After a (re)start we
    skip probing for `grace` seconds because a fresh tunnel takes a few seconds
    to become reachable. Named tunnels come back on the SAME url; quick tunnels
    get a fresh random url, which we reprint prominently.
    """
    fails = 0
    last_start = time.time()

    while not stop_event.is_set():
        if stop_event.wait(interval):
            break

        proc: subprocess.Popen = holder["proc"]
        url: str = holder["url"]
        proc_dead = proc.poll() is not None

        if not proc_dead:
            if time.time() - last_start < grace:
                continue
            if probe_public(url):
                fails = 0
                continue
            fails += 1
            print(
                f"[run_colab] tunnel probe failed ({fails}/{threshold}) for {url}",
                flush=True,
            )
            if fails < threshold:
                continue
        else:
            print("[run_colab] cloudflared process has exited", flush=True)

        print("[run_colab] tunnel looks down; restarting cloudflared ...", flush=True)
        _terminate(proc)
        try:
            new_proc, new_url = spawn()
        except Exception as exc:  # noqa: BLE001 - keep the supervisor alive
            print(f"[run_colab] tunnel restart failed: {exc}; retrying next cycle", flush=True)
            fails = 0
            last_start = time.time()  # honor grace before the next probe attempt
            continue

        holder["proc"] = new_proc
        holder["url"] = new_url
        fails = 0
        last_start = time.time()
        if new_url == url:
            print(f"[run_colab] tunnel restored on {new_url}", flush=True)
        else:
            print("=" * 70, flush=True)
            print(f"FLUX tunnel RESTARTED. NEW public URL: {new_url}", flush=True)
            print("(the previous URL is dead — switch to this one)", flush=True)
            print("=" * 70, flush=True)


def wait_for_port(host: str, port: int, timeout: float = 1800.0) -> None:
    """Poll until the TCP port accepts connections (uvicorn has finished startup)."""
    deadline = time.time() + timeout
    last_log = 0.0
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            now = time.time()
            if now - last_log >= 15:
                remaining = int(deadline - now)
                print(
                    f"[run_colab] still waiting for uvicorn on {host}:{port} "
                    f"(pipeline load in progress, {remaining}s budget left)...",
                    flush=True,
                )
                last_log = now
            time.sleep(1)
    raise RuntimeError(f"timed out waiting for {host}:{port}")


def main() -> int:
    port = int(os.environ.get("FLUX_PORT", "8000"))
    token = os.environ.get("FLUX_TOKEN") or config.generate_token()
    os.environ["FLUX_TOKEN"] = token

    bin_path = ensure_cloudflared()

    import uvicorn

    uv_config = uvicorn.Config("app.main:app", host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(uv_config)

    server_thread = threading.Thread(target=server.run, name="uvicorn", daemon=False)
    server_thread.start()

    print(
        f"[run_colab] uvicorn starting; pipeline load takes a few minutes on first run. "
        f"Tunnel will open once http://127.0.0.1:{port} is listening.",
        flush=True,
    )

    try:
        wait_for_port("127.0.0.1", port)
    except Exception:
        server.should_exit = True
        server_thread.join(timeout=10)
        raise

    # Pick the tunnel mode. Named (stable URL) when a token is provided,
    # otherwise the zero-config quick tunnel. `spawn` builds a fresh tunnel of
    # the chosen mode; the supervisor calls it on every restart.
    cf_token = resolve_cf_token()
    if cf_token:
        hostname = (os.environ.get("TUNNEL_HOSTNAME") or DEFAULT_TUNNEL_HOSTNAME).strip()
        if not hostname:
            server.should_exit = True
            server_thread.join(timeout=10)
            raise RuntimeError(
                "A Cloudflare tunnel token was found but TUNNEL_HOSTNAME is empty. "
                "Set TUNNEL_HOSTNAME to the Public Hostname you configured in the "
                "Cloudflare dashboard, e.g. flux.codecrab.dev"
            )
        mode = f"named tunnel ({hostname})"

        def spawn() -> tuple[subprocess.Popen, str]:
            return start_named_tunnel(bin_path, cf_token, hostname)
    else:
        mode = "quick tunnel (trycloudflare.com, URL changes on restart)"

        def spawn() -> tuple[subprocess.Popen, str]:
            return start_tunnel(bin_path, port)

    print(f"[run_colab] uvicorn is ready; opening {mode}...", flush=True)
    tunnel_proc, public_url = spawn()

    # Shared, mutable so the supervisor can swap in a fresh tunnel on restart
    # while the signal handler / shutdown path still see the live process.
    holder = {"proc": tunnel_proc, "url": public_url}

    print("=" * 70, flush=True)
    print(f"FLUX Image Generator is publishing on: {public_url}", flush=True)
    print(f"Bearer token:                          {token}", flush=True)
    print("=" * 70, flush=True)

    stop_event = threading.Event()
    supervisor = threading.Thread(
        target=supervise_tunnel,
        args=(spawn, holder, stop_event),
        name="tunnel-supervisor",
        daemon=True,
    )
    supervisor.start()

    def _handle_sig(_signum, _frame):
        stop_event.set()
        _terminate(holder["proc"])
        server.should_exit = True

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    try:
        server_thread.join()
    finally:
        stop_event.set()
        _terminate(holder["proc"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
