# Contributing

```
uv sync --all-extras
uv run ruff check .
QT_QPA_PLATFORM=offscreen uv run pytest
uv run python main.py
```

Keep commits small and verifiable; add or update tests with every behavior change.
