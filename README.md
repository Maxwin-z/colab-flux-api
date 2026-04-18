# FLUX Image Generator (Colab)

A small FastAPI service wrapping FLUX.1 [schnell] on a Colab L4 GPU, with a web UI at `/` and REST endpoints for txt2img / img2img.

## Run on Colab

```python
!pip install -r requirements.txt -q
!python run_colab.py
```

The script prints a TryCloudflare public URL and a Bearer token. Open the URL, paste the token when prompted.

## Run locally for development (no GPU)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```
