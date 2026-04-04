# AGENTS.md

Guidelines for AI coding assistants working in this repository.

## Project Overview

Audio Summary with Local LLM - A CLI tool that transcribes and summarizes audio/video files using OpenAI Whisper and local LLMs (default: gpt-oss:120b via Ollama).

## Build Commands

- `uv sync` - Install/sync dependencies
- `uv run audio-summary [OPTIONS]` - Run CLI (e.g., `uv run audio-summary --from-youtube <URL>`)
- `pipx install -e .` - Install globally (editable mode)

## Lint/Format Commands

- `uv run ruff check .` - Run linter
- `uv run ruff check . --fix` - Fix auto-fixable issues
- `uv run ruff format .` - Format all files
- `uv run ruff format src/audio_summary/cli.py` - Format single file

**Note:** Tests use pytest. Run with `uv run pytest`.

## Ollama Configuration

The tool supports both local Ollama and Ollama Cloud via environment variables:
- `OLLAMA_HOST` - Ollama server URL (default: `http://localhost:11434`)
- `OLLAMA_API_KEY` - API key for Ollama Cloud authentication

The `get_ollama_client()` function in cli.py creates an authenticated client using these environment variables.

## Code Style Guidelines

### Imports
- Group imports: stdlib → third-party → local
- Use `from pathlib import Path` over `os.path`
- Example:
  ```python
  import argparse
  from pathlib import Path
  import sys

  import ollama
  from transformers import pipeline
  import torch
  ```

### Formatting
- **Line length:** 88 characters (Black-compatible)
- **Indent:** 4 spaces
- **Quotes:** Double quotes preferred
- Ruff enforces all formatting automatically

### Type Hints
- Use Python 3.10+ union syntax: `str | None` instead of `Optional[str]`
- Always annotate function parameters and return types
- Example: `def transcribe_file(file_path: str, language: str | None = None) -> str:`

### Naming Conventions
- **Constants:** `UPPER_SNAKE_CASE` (e.g., `OLLAMA_MODEL`, `WHISPER_MODEL`)
- **Functions/Variables:** `snake_case` (e.g., `download_from_youtube`, `transcript`)
- **Classes:** `PascalCase` when needed

### Error Handling
- Pattern for operations: try/except → print error → sys.exit(1)
- Pattern for CLI validation: `parser.error("message")`
- Example:
  ```python
  try:
      result = operation()
  except Exception as e:
      print(f"Error during operation: {e}")
      sys.exit(1)
  ```

### Comments
- Use full sentences with capitalization
- Explain "why" not just "what"
- Inline comments for complex logic

### Strings
- Use f-strings for interpolation
- Double quotes for string literals

### File Operations
- Always use `pathlib.Path` instead of os.path
- Check file existence: `Path(path).is_file()`
- Create directories: `path.mkdir(parents=True, exist_ok=True)`

## Project Structure

```
src/audio_summary/
├── __init__.py     # Package version
└── cli.py          # Main CLI implementation
```

## Key Configuration

- **Python version:** >=3.12, <3.13
- **Package manager:** uv (preferred) or pip
- **Build system:** setuptools
- **CLI entry point:** `audio-summary` → `audio_summary.cli:main`
- **Default LLM:** gpt-oss:120b (via Ollama, supports both local and Ollama Cloud)

## Pre-commit Checklist

Before finishing work:
1. Run `uv run ruff check . --fix` to fix linting issues
2. Run `uv run ruff format .` to ensure consistent formatting
3. Verify CLI runs: `uv run audio-summary --help`

## Dependencies

Main: ffmpeg, ollama, openai-whisper, torch, transformers, yt-dlp
Dev: ruff (lint), ipython
