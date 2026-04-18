"""BS Calibration Engine — compare Black-Scholes theoretical prices vs real market data.

Given a ticker and date range, fetches historical option chains from Databento
and compares the BS theoretical price (using VIX6M as IV) against the actual
market mid price. Reports per-date and aggregate deviation statistics.

Usage:
    python scripts/calibrate_bs.py --ticker SPY --start 2023-01-01 --end 2023-12-31
    python scripts/calibrate_bs.py --ticker SPY --dates 2024-01-15,2024-06-20
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class CalibrationPoint:
    date: str
    ticker: str
    strike: float
    expiry: str
    option_type: str
    spot: float
    bs_price: float
    market_mid: float
    market_bid: float
    market_ask: float
    bs_iv: float
    market_iv: Optional[float]
    delta: Optional[float]
    abs_error: float
    pct_error: float


@dataclass
class CalibrationReport:
    ticker: str
    points: list[CalibrationPoint]
    summary: dict

    def to_dataframe(self) -> pd.DataFrame:
        if not self.points:
            return pd.DataFrame()
        return pd.DataFrame([
            {
                "date": p.date, "strike": p.strike, "expiry": p.expiry,
                "type": p.option_type, "spot": p.spot,
                "bs_price": round(p.bs_price, 2),
                "mkt_mid": round(p.market_mid, 2),
                "mkt_bid": round(p.market_bid, 2),
                "mkt_ask": round(p.market_ask, 2),
                "abs_err": round(p.abs_error, 2),
                "pct_err": round(p.pct_error, 2),
                "bs_iv": round(p.bs_iv, 4) if p.bs_iv else None,
                "mkt_iv": round(p.market_iv, 4) if p.market_iv else None,
                "delta": round(p.delta, 3) if p.delta else None,
            }
            for p in self.points
        ])

    def print_summary(self) -> None:
        s = self.summary
        print(f"\n{'='*65}")
        print(f"  BS Calibration Report — {self.ticker}")
        print(f"{'='*65}")
        print(f"  Data points        : {s['n_points']}")
        print(f"  Date range         : {s['date_range']}")
        print(f"  Mean abs error     : ${s['mean_abs_error']:.2f}")
        print(f"  Median abs error   : ${s['median_abs_error']:.2f}")
        print(f"  Mean pct error     : {s['mean_pct_error']:.1f}%")
        print(f"  Median pct error   : {s['median_pct_error']:.1f}%")
        print(f"  P90 pct error      : {s['p90_pct_error']:.1f}%")
        print(f"  Within bid-ask     : {s['within_spread_pct']:.0f}%")
        print(f"  BS overestimates   : {s['overestimate_pct']:.0f}%")
        print(f"  BS underestimates  : {s['underestimate_pct']:.0f}%")
        print()

        if s.get("by_delta"):
            print("  Error by delta bucket:")
            print(f"  {'Delta':<12} {'Mean %Err':>10} {'N':>6}")
            print(f"  {'-'*30}")
            for bucket, stats in s["by_delta"].items():
                print(f"  {bucket:<12} {stats['mean_pct']:.1f}%{stats['n']:>8}")
            print()


class BSCalibrator:
    """Compares BS theoretical option prices against real Databento market data."""

    def __init__(self, databento_api_key: str):
        from data.providers.databento_provider import DatabentoProvider
        self._provider = DatabentoProvider(api_key=databento_api_key)

    async def calibrate(
        self,
        ticker: str,
        dates: list[str],
        delta_target: float = 0.80,
        expiry_months_min: int = 3,
        expiry_months_max: int = 9,
        risk_free_rate: float = 0.043,
    ) -> CalibrationReport:
        """Run calibration across multiple dates.

        For each date, finds option contracts near the target delta with
        expiry in the specified range, and compares BS price vs market mid.
        """
        from backtest.strategies.leap_simulator import bs_call_price, bs_call_delta

        all_points: list[CalibrationPoint] = []

        for date_str in dates:
            logger.info("Calibrating %s on %s ...", ticker, date_str)

            snap = await self._provider.get_historical_option_chain(
                ticker, date=date_str, risk_free_rate=risk_free_rate,
            )
            if snap is None or not snap.calls:
                logger.warning("No option data for %s on %s", ticker, date_str)
                continue

            spot = self._estimate_spot(snap)
            if spot is None or spot <= 0:
                logger.warning("Cannot determine spot for %s on %s", ticker, date_str)
                continue

            ref_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            min_dte = expiry_months_min * 30
            max_dte = expiry_months_max * 30

            for c in snap.calls:
                if c.bid <= 0 or c.ask <= 0:
                    continue

                exp_dt = datetime.strptime(c.expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                dte = (exp_dt - ref_date).days
                if dte < min_dte or dte > max_dte:
                    continue

                T = dte / 365.0
                mid = (c.bid + c.ask) / 2

                mkt_iv = c.implied_volatility
                if mkt_iv is None or mkt_iv <= 0:
                    continue

                bs_price = bs_call_price(spot, c.strike, T, risk_free_rate, mkt_iv)
                delta = bs_call_delta(spot, c.strike, T, risk_free_rate, mkt_iv)

                if delta < 0.20 or delta > 0.95:
                    continue

                abs_err = bs_price - mid
                pct_err = (abs_err / mid * 100) if mid > 0 else 0

                all_points.append(CalibrationPoint(
                    date=date_str, ticker=ticker, strike=c.strike,
                    expiry=c.expiry, option_type="call", spot=spot,
                    bs_price=bs_price, market_mid=mid,
                    market_bid=c.bid, market_ask=c.ask,
                    bs_iv=mkt_iv, market_iv=mkt_iv, delta=delta,
                    abs_error=abs_err, pct_error=pct_err,
                ))

        summary = self._compute_summary(all_points)
        return CalibrationReport(ticker=ticker, points=all_points, summary=summary)

    def _estimate_spot(self, snap) -> Optional[float]:
        """Estimate spot from ATM call option prices (put-call parity approximation)."""
        if not snap.calls:
            return None
        atm_calls = [c for c in snap.calls if c.bid > 0 and c.ask > 0]
        if not atm_calls:
            return None
        by_moneyness = sorted(atm_calls, key=lambda c: abs(c.strike - (c.bid + c.ask) / 2 - c.strike))
        best = by_moneyness[0]
        return best.strike + (best.bid + best.ask) / 2

    @staticmethod
    def _compute_summary(points: list[CalibrationPoint]) -> dict:
        if not points:
            return {"n_points": 0, "date_range": "N/A"}

        pct_errors = [abs(p.pct_error) for p in points]
        abs_errors = [abs(p.abs_error) for p in points]
        within_spread = sum(
            1 for p in points
            if p.market_bid <= p.bs_price <= p.market_ask
        )

        delta_buckets = {
            "0.20-0.40": [], "0.40-0.60": [],
            "0.60-0.80": [], "0.80-0.95": [],
        }
        for p in points:
            if p.delta is None:
                continue
            if p.delta < 0.40:
                delta_buckets["0.20-0.40"].append(abs(p.pct_error))
            elif p.delta < 0.60:
                delta_buckets["0.40-0.60"].append(abs(p.pct_error))
            elif p.delta < 0.80:
                delta_buckets["0.60-0.80"].append(abs(p.pct_error))
            else:
                delta_buckets["0.80-0.95"].append(abs(p.pct_error))

        by_delta = {}
        for bucket, errs in delta_buckets.items():
            if errs:
                by_delta[bucket] = {
                    "mean_pct": float(np.mean(errs)),
                    "n": len(errs),
                }

        dates = sorted({p.date for p in points})

        return {
            "n_points": len(points),
            "date_range": f"{dates[0]} to {dates[-1]}" if len(dates) > 1 else dates[0],
            "mean_abs_error": float(np.mean(abs_errors)),
            "median_abs_error": float(np.median(abs_errors)),
            "mean_pct_error": float(np.mean(pct_errors)),
            "median_pct_error": float(np.median(pct_errors)),
            "p90_pct_error": float(np.percentile(pct_errors, 90)),
            "within_spread_pct": within_spread / len(points) * 100,
            "overestimate_pct": sum(1 for p in points if p.pct_error > 0) / len(points) * 100,
            "underestimate_pct": sum(1 for p in points if p.pct_error < 0) / len(points) * 100,
            "by_delta": by_delta,
        }
