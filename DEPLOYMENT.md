# Deployment

## Local Development

The primary use case is local analysis on a personal machine:

```bash
pip install -r requirements.txt
python scripts/run_pipeline.py --query "crater" --max 50
```

## Standalone EXE Distribution

Build a portable EXE that requires no Python installation:

```bash
pip install -e .[dev]
python scripts/build_app.py --fullstack --onefile
# Output: dist/nasa-fullstack.exe
```

Distribute the single file. Data stays next to the EXE.

### EXE Build Targets

| Command | Output | Description |
|---------|--------|-------------|
| `python scripts/build_app.py` | `dist/nasa-pipeline/` | Pipeline CLI only |
| `python scripts/build_app.py --fullstack` | `dist/nasa-fullstack/` | Dashboard + pipeline |
| `python scripts/build_app.py --onefile` | Single `.exe` | Portable single file |
| `python scripts/build_app.py --bot` | `dist/nasa-bot/` | Discord bot |

### Full-Stack Server

```bash
pip install fastapi uvicorn
python scripts/build_app.py --fullstack
dist/nasa-fullstack/nasa-fullstack.exe
# Opens http://127.0.0.1:8000
```

### Server Options

```bash
nasa-fullstack.exe --port 3000           # Custom port
nasa-fullstack.exe --no-browser          # Don't open browser
nasa-fullstack.exe --cli                 # CLI mode instead of server
nasa-fullstack.exe --from detect --to adjudicate  # CLI with step range
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard UI |
| `/docs` | GET | Swagger documentation |
| `/api/analyze` | POST | Instant image analysis |
| `/api/pipeline/run` | POST | Run full pipeline |
| `/api/pipeline/status` | GET | Current pipeline status |
| `/showcase/` | GET | Investigation showcase |

### Discord Bot

```bash
pip install discord.py aiohttp
$env:DISCORD_TOKEN = "<your-token>"
python bot/discord_bot.py
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NASA_HOST` | `127.0.0.1` | Server bind host |
| `NASA_PORT` | `8000` | Server bind port |
| `DISCORD_TOKEN` | — | Discord bot token |
| `AI_LLM_KEY` | — | Vision LLM API key |

## Security Notes

- Server binds to localhost only by default
- No authentication — intended for local use
- Do not expose to the internet without adding auth
- All secrets via environment variables, never hardcoded
