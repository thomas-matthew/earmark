# Earmark

Turns saved bookmarks from X, Reddit, Substack and Hacker News into a private podcast, one retold episode per item. Requirements are frozen in [REQUIREMENTS.md](REQUIREMENTS.md); the application itself is not built yet.

## Setup

Requires an Apple Silicon Mac and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

Python and packages stay inside this folder, in `.venv/`. Models are shared across projects in the folder named by `HF_HOME` (`~/Dev/labs/huggingface` on my Mac) and download on first use.

Logins for X, Reddit and Substack go in `.env`, which is never committed.

## Experiments

`experiments/` holds throwaway prototypes used to test feasibility. They are not the final design, and still use the project's working name, Bookcast, internally.

```bash
cd experiments
uv run python -m unittest test_bookcast
uv run python bookcast.py add "https://example.com/article"
uv run python bookcast.py run
```
