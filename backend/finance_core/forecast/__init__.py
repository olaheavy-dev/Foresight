"""Cash-flow forecast engine (docs/07 §6): deterministic for a given input and seed."""

from backend.finance_core.forecast.backtest import backtest
from backend.finance_core.forecast.engine import ENGINE_VERSION, build_forecast

__all__ = ["ENGINE_VERSION", "backtest", "build_forecast"]
