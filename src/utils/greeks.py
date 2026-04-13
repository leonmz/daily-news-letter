"""Black-Scholes option pricing and Greeks via BSM."""

import math
from typing import Optional
from scipy.stats import norm
from scipy.optimize import brentq


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> tuple[float, float]:
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    return d1, d1 - sigma * math.sqrt(T)


def _bs_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    if T <= 0:
        return max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    if option_type == "call":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def implied_vol(
    S: float, K: float, T: float, r: float,
    market_price: float, option_type: str = "call",
) -> Optional[float]:
    """Back-calculate IV from market price via Brent's method. Returns None if unsolvable."""
    if T <= 0 or market_price <= 0:
        return None

    intrinsic = max(S - K * math.exp(-r * T), 0.0) if option_type == "call" else max(K * math.exp(-r * T) - S, 0.0)
    if market_price - intrinsic < 0.02:
        return None

    try:
        return brentq(
            lambda sigma: _bs_price(S, K, T, r, sigma, option_type) - market_price,
            1e-4, 5.0, xtol=1e-6, maxiter=200,
        )
    except (ValueError, RuntimeError):
        return None


def bs_greeks(
    S: float, K: float, T: float, r: float,
    sigma: float, option_type: str = "call",
) -> dict:
    """Compute delta, gamma, theta, vega, rho for a European option."""
    if T <= 0 or sigma <= 0:
        return {
            "delta": (1.0 if S > K else 0.0) if option_type == "call" else (-1.0 if S < K else 0.0),
            "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0,
        }

    d1, d2 = _d1_d2(S, K, T, r, sigma)
    sqrt_T = math.sqrt(T)
    exp_rT = math.exp(-r * T)
    pdf_d1 = norm.pdf(d1)
    is_call = option_type == "call"

    delta = norm.cdf(d1) if is_call else norm.cdf(d1) - 1
    gamma = pdf_d1 / (S * sigma * sqrt_T)
    common_theta = -(S * pdf_d1 * sigma) / (2 * sqrt_T)
    theta = (common_theta - r * K * exp_rT * norm.cdf(d2)) / 365 if is_call \
        else (common_theta + r * K * exp_rT * norm.cdf(-d2)) / 365
    vega = S * pdf_d1 * sqrt_T / 100
    rho = (K * T * exp_rT * norm.cdf(d2) / 100) if is_call \
        else (-K * T * exp_rT * norm.cdf(-d2) / 100)

    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega, "rho": rho}
