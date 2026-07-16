# FLUX Image Generator (Colab)

A small FastAPI service wrapping FLUX.1 [schnell] on a Colab L4 GPU, with a web UI at `/` and REST endpoints for txt2img / img2img.

## Run on Colab

### One-click (stable URL `https://flux.codecrab.dev`)

One-time setup: in Colab's **Secrets** panel (🔑, left sidebar) add a secret named
`CLOUDFLARE_TUNNEL_TOKEN`, paste the tunnel token, and toggle **Notebook access** on.
Then every run is a single cell:

```python
import os
from google.colab import userdata
os.environ["CLOUDFLARE_TUNNEL_TOKEN"] = userdata.get("CLOUDFLARE_TUNNEL_TOKEN")
!pip install -r requirements.txt -q && python run_colab.py
```

The FLUX pipeline loads (a few minutes), then the log prints
`publishing on https://flux.codecrab.dev`. That hostname is fixed and survives
restarts. A background supervisor keeps the tunnel alive: if cloudflared dies or
the public URL stops answering `/healthz`, it restarts the tunnel automatically
(same URL). Open the URL, paste the Bearer token (also printed) when prompted.

> `TUNNEL_HOSTNAME` defaults to `flux.codecrab.dev` (see `run_colab.py`); set that
> env var to override. `run_colab.py` also reads `CLOUDFLARE_TUNNEL_TOKEN`
> straight from Colab Secrets, so the `userdata` line above is only needed if the
> secret isn't picked up automatically in your runtime.

### Zero-config fallback (ephemeral URL)

With **no** token configured, the script falls back to a free TryCloudflare quick
tunnel and prints a random `*.trycloudflare.com` URL. Instant and account-free,
but the URL **changes on every restart** and the free tunnel is less stable.

```python
!pip install -r requirements.txt -q && python run_colab.py
```

### One-time Cloudflare dashboard setup (for the named tunnel)

Cloudflare **Zero Trust → Networks → Tunnels**:
1. **Create a tunnel** → connector type **Cloudflared** → name it (e.g. `colab-flux`).
   Copy the **token** (the long `eyJ…` string after `--token`) into the Colab Secret above.
2. On the tunnel's **Public Hostname** tab, add one:
   - Subdomain `flux`, Domain `codecrab.dev`
   - Service: **HTTP** → `localhost:8000` (must match `FLUX_PORT`)
   Cloudflare creates the `flux.codecrab.dev` DNS record for you. WebSocket works by default.

## Run locally for development (no GPU)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```
