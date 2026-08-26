# Security Policy

## Reporting Vulnerabilities

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT open a public issue** for security vulnerabilities
2. Email the maintainers or use GitHub's private vulnerability reporting
3. Include: description, steps to reproduce, potential impact

We will respond within 72 hours and work with you to understand and address the issue.

## Scope

This project is a **local analysis pipeline** for planetary imagery. It is not designed for:
- Internet-facing production deployments
- Multi-user authentication scenarios
- Storing sensitive user data

However, we take security seriously and address all valid reports.

## Known Security Considerations

### Network Access

- The full-stack server binds to `127.0.0.1:8000` by default (localhost only)
- CORS is set to `*` — acceptable for localhost-only usage
- No authentication is implemented — this is intentional for a local tool

### API Keys

- `DISCORD_TOKEN` — for Discord bot integration (optional)
- `AI_LLM_KEY` — for vision LLM analysis (optional)
- Both are loaded from environment variables, never hardcoded

### File System

- Input validation uses `common.contain_path()` to prevent path traversal
- Atomic writes prevent race conditions on output files
- Audit trail tracks all pipeline operations

### Dependencies

- Only well-maintained packages (numpy, Pillow, scipy, FastAPI, discord.py)
- Optional dependencies degrade gracefully when absent
- No known vulnerabilities in current dependency versions

## Best Practices for Users

1. Run the pipeline on a local machine, not a shared server
2. Use a virtual environment: `python -m venv .venv`
3. Keep dependencies updated: `pip install -U -r requirements.txt`
4. Do not expose the API to the internet
5. Use environment variables for API tokens

## Version Support

| Version | Supported |
|---------|-----------|
| 1.4.x   | Yes       |
| < 1.4   | No        |
