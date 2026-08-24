"""Allow `python -m agent_eval` to run the unified evaluation CLI."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
