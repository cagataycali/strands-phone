# Contributing

Thanks for helping. Small, focused pull requests are easiest to review.

```bash
uv venv -p 3.12 && uv pip install -e '.[dev,openai]'
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -q            # includes a real SIP + RTP loopback call on localhost
```

- **Code:** Python 3.12+ and stdlib-first. The SIP, RTP and G.711 code depends on nothing but the standard library;
  keep it that way.
- **Tests:** a behaviour change comes with a test. Network behaviour belongs in `tests/test_loopback.py`, which uses
  stub agents, so it needs no AWS or OpenAI account.
- **Docs:** pages live in `docs/`. Drawings are code: edit `design/drawings/scenes/p0*.py`, then run
  `python3 design/drawings/scene.py --all` and commit the regenerated SVGs. CI fails when an SVG drifts from its
  scene, or when a drawing uses a name the docs never mention (`--check docs`).
- **Numbers:** anything you put in a doc as measured needs output you can show.
- **Secrets:** never commit `.state.env`, `.secrets.env` or call recordings. `.gitignore` covers them.

By contributing, you agree that your contributions are licensed under the Apache License 2.0.
