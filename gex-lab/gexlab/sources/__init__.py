"""Chain sources. Each exposes fetch(ticker, ...) -> Chain and describe(payload).

`describe` is what the `doctor` command uses: it reports what the raw payload
actually contained versus what the parser expects, so a schema change upstream
is diagnosed in one command instead of a stack trace mid-scan.
"""

from . import cboe, local, yahoo

REGISTRY = {"cboe": cboe, "yahoo": yahoo, "csv": local}

__all__ = ["cboe", "yahoo", "local", "REGISTRY"]
