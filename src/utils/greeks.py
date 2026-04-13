"""
Black-Scholes option pricing and Greeks.

All functions use the standard BSM model for European options.
IV is back-calculated from market price via Brent's method — this avoids
the systematic error in yfinance's impliedVolatility field for deep-ITM
LEAP options, where extrinsic value is tiny and yfinance's approximation
breaks down.
"""

import math
from typing import Optional
from scipy.stats import norm
from scipy.optimize import brentq

__all__ = ["bs_greeks", "implied_vol", "bs_call_delta"]


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> tuple[float, float]:
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def bs_call_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0:
        return max(S - K, 0.0)
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)


def implied_vol(
    S: float,
    K: float,
    T: float,
    r: float,
    market_price: float,
    option_type: str = "call",
) -> Optional[float]:
    """
    Back-calculate implied volatility from a market price using Brent's method.

    Returns None when:
    - The option has negligible extrinsic value (deep ITM, price ≈ intrinsic)
    - No solution exists in [0.001, 5.0] (500% IV ceiling)
    """
    if T <= 0 or market_price <= 0:
        return None

    intrinsic = max(S - K * math.exp(-r * T), 0.0) if option_type == "call" else max(K * math.exp(-r * T) - S, 0.0)
    extrinsic = market_price - intrinsic

    # Need at least $0.02 of time value to get a meaningful IV
    if extrinsic < 0.02:
        return None

    try:
        iv = brentq(
            lambda sigma: bs_call_price(S, K, T, r, sigma) - market_price
            if option_type == "call"
            else _bs_put_price(S, K, T, r, sigma) - market_price,
            1e-4, 5.0,
            xtol=1e-6,
            maxiter=200,
        )
        return iv
    except (ValueError, RuntimeError):
        return None


def _bs_put_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0:
        return max(K - S, 0.0)
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def bs_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
) -> dict:
    """
    Compute full Greeks for a European option using BSM.

    Returns:
        delta:  price sensitivity to underlying (0–1 for calls, -1–0 for puts)
        gamma:  delta sensitivity to underlying (same for calls and puts)
        theta:  daily time decay (in dollars, per calendar day)
        vega:   price sensitivity to 1% move in IV (in dollars)
        rho:    price sensitivity to 1% move in risk-free rate (in dollars)
    """
    if T <= 0 or sigma <= 0:
        return {
            "delta": (1.0 if S > K else 0.0) if option_type == "call" else (-1.0 if S < K else 0.0),
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "rho": 0.0,
        }

    d1, d2 = _d1_d2(S, K, T, r, sigma)
    sqrt_T  = math.sqrt(T)
    exp_rT  = math.exp(-r * T)
    pdf_d1  = norm.pdf(d1)

    # Delta
    delta = norm.cdf(d1) if option_type == "call" else norm.cdf(d1) - 1

    # Gamma (same for calls and puts)
    gamma = pdf_d1 / (S * sigma * sqrt_T)

    # Theta (per calendar day; BSM formula gives per year, divide by 365)
    if option_type == "call":
        theta = (
            -(S * pdf_d1 * sigma) / (2 * sqrt_T)
            - r * K * exp_rT * norm.cdf(d2)
        ) / 365
    else:
        theta = (
            -(S * pdf_d1 * sigma) / (2 * sqrt_T)
            + r * K * exp_rT * norm.cdf(-d2)
        ) / 365

    # Vega (per 1% change in IV, i.e. divide by 100)
    vega = S * pdf_d1 * sqrt_T / 100

    # Rho (per 1% change in r, i.e. divide by 100)
    if option_type == "call":
        rho = K * T * exp_rT * norm.cdf(d2) / 100
    else:
        rho = -K * T * exp_rT * norm.cdf(-d2) / 100

    return {
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "rho": rho,
    }


def bs_call_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Convenience wrapper — call delta only."""
    return bs_greeks(S, K, T, r, sigma, "call")["delta"]
