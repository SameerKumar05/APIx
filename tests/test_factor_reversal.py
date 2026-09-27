"""Factor reversal: what holds, what does not, and why.

The master specification marks Factor Reversal as passing. That claim had no
evidence behind it, and this file establishes both the identity and the reason
the engine cannot currently satisfy it.

The identity itself is real. For the *true* Laspeyres and Paasche price indices,
the Fisher ideal satisfies P_F * Q_F == V_t / V_0 exactly. The first test proves
that with quantities supplied, so nobody has to take it on faith.

The engine does not satisfy it, and the reason is structural rather than a
missing test. calculate_paasche_index computes the true Paasche,
sum(p_t * q_t) / sum(p_0 * q_t). calculate_laspeyres_index computes
sum(w_r * (p_t / p_0)) over normalised weights, which is a fixed-weight mean of
price relatives, not sum(p_t * q_0) / sum(p_0 * q_0). The two agree only when
every price relative is identical, so the "Fisher" of the pair is not the Fisher
ideal price index and factor reversal does not hold.

These tests pin that characterisation so the deviation cannot be quietly
re-labelled as a pass.
"""

from __future__ import annotations

import math

import pytest

from backend.app.services.econometric_engine import (
    calculate_fisher_index,
    calculate_paasche_index,
)
from backend.app.services.index_engine import (
    calculate_laspeyres_index,
    calculate_true_laspeyres_index,
)

BASE_PRICES = {"DEL-BOM": 4200.0, "DEL-BLR": 5100.0, "BOM-BLR": 3400.0}
BASE_QUANTITIES = {"DEL-BOM": 437_500.0, "DEL-BLR": 312_500.0, "BOM-BLR": 225_000.0}
CURRENT_PRICES = {"DEL-BOM": 5040.0, "DEL-BLR": 5610.0, "BOM-BLR": 3740.0}
CURRENT_QUANTITIES = {"DEL-BOM": 470_000.0, "DEL-BLR": 300_000.0, "BOM-BLR": 260_000.0}


def _shares(values: dict[str, float]) -> dict[str, float]:
    total = sum(values.values())
    return {k: v / total for k, v in values.items()}


def _laspeyres(
    x0: dict[str, float], xt: dict[str, float], w0: dict[str, float]
) -> float:
    """Textbook Laspeyres for variable X under base-period weights W0."""
    keys = x0.keys()
    return sum(xt[r] * w0[r] for r in keys) / sum(x0[r] * w0[r] for r in keys)


def _paasche(x0: dict[str, float], xt: dict[str, float], wt: dict[str, float]) -> float:
    """Textbook Paasche for variable X under current-period weights Wt."""
    keys = x0.keys()
    return sum(xt[r] * wt[r] for r in keys) / sum(x0[r] * wt[r] for r in keys)


def _price_fisher() -> float:
    return math.sqrt(
        _laspeyres(BASE_PRICES, CURRENT_PRICES, BASE_QUANTITIES)
        * _paasche(BASE_PRICES, CURRENT_PRICES, CURRENT_QUANTITIES)
    )


def _quantity_fisher() -> float:
    return math.sqrt(
        _laspeyres(BASE_QUANTITIES, CURRENT_QUANTITIES, BASE_PRICES)
        * _paasche(BASE_QUANTITIES, CURRENT_QUANTITIES, CURRENT_PRICES)
    )


def _value_ratio() -> float:
    keys = BASE_PRICES.keys()
    current = sum(CURRENT_PRICES[r] * CURRENT_QUANTITIES[r] for r in keys)
    base = sum(BASE_PRICES[r] * BASE_QUANTITIES[r] for r in keys)
    return current / base


def test_factor_reversal_holds_for_the_true_laspeyres_paasche_pair() -> None:
    """The identity is achievable, so the engine's deviation is the explanation."""
    assert _price_fisher() * _quantity_fisher() == pytest.approx(
        _value_ratio(), rel=1e-12
    )


def test_engine_paasche_is_the_true_paasche() -> None:
    engine = calculate_paasche_index(
        CURRENT_PRICES, BASE_PRICES, _shares(CURRENT_QUANTITIES)
    )
    assert engine == pytest.approx(
        _paasche(BASE_PRICES, CURRENT_PRICES, CURRENT_QUANTITIES) * 100.0
    )


def test_engine_laspeyres_is_a_relative_mean_not_a_true_laspeyres() -> None:
    """Documents the defect. If this ever stops holding, the engine changed."""
    engine = calculate_laspeyres_index(
        CURRENT_PRICES, BASE_PRICES, _shares(BASE_QUANTITIES)
    )
    true_laspeyres = _laspeyres(BASE_PRICES, CURRENT_PRICES, BASE_QUANTITIES) * 100.0
    assert engine != pytest.approx(true_laspeyres, rel=1e-9)


def test_engine_laspeyres_matches_true_laspeyres_only_when_relatives_are_uniform() -> (
    None
):
    """Why the deviation hides: identical relatives make the two formulas coincide."""
    uniform = {r: v * 1.2 for r, v in BASE_PRICES.items()}
    engine = calculate_laspeyres_index(uniform, BASE_PRICES, _shares(BASE_QUANTITIES))
    true_laspeyres = _laspeyres(BASE_PRICES, uniform, BASE_QUANTITIES) * 100.0
    assert engine == pytest.approx(true_laspeyres, rel=1e-12)


def test_engine_fisher_pair_does_not_satisfy_factor_reversal() -> None:
    """The claim in the master specification is false, and this is the counterexample."""
    price_fisher = calculate_fisher_index(
        calculate_laspeyres_index(
            CURRENT_PRICES, BASE_PRICES, _shares(BASE_QUANTITIES)
        ),
        calculate_paasche_index(
            CURRENT_PRICES, BASE_PRICES, _shares(CURRENT_QUANTITIES)
        ),
    )
    quantity_fisher = calculate_fisher_index(
        calculate_laspeyres_index(
            CURRENT_QUANTITIES, BASE_QUANTITIES, _shares(BASE_PRICES)
        ),
        calculate_paasche_index(
            CURRENT_QUANTITIES, BASE_QUANTITIES, _shares(CURRENT_PRICES)
        ),
    )
    product = (price_fisher / 100.0) * (quantity_fisher / 100.0)
    assert product != pytest.approx(_value_ratio(), rel=1e-6)


def test_engine_true_laspeyres_matches_textbook_laspeyres() -> None:
    """True Laspeyres function matches textbook formula sum(p_t * q_0) / sum(p_0 * q_0) * 100."""
    engine = calculate_true_laspeyres_index(
        CURRENT_PRICES, BASE_PRICES, BASE_QUANTITIES
    )
    textbook = _laspeyres(BASE_PRICES, CURRENT_PRICES, BASE_QUANTITIES) * 100.0
    assert engine == pytest.approx(textbook, rel=1e-12)


def test_engine_true_laspeyres_satisfies_fisher_factor_reversal() -> None:
    """When True Laspeyres is paired with Paasche, the Fisher pair satisfies factor reversal identically."""
    price_fisher = calculate_fisher_index(
        calculate_true_laspeyres_index(CURRENT_PRICES, BASE_PRICES, BASE_QUANTITIES),
        calculate_paasche_index(CURRENT_PRICES, BASE_PRICES, CURRENT_QUANTITIES),
    )
    quantity_fisher = calculate_fisher_index(
        calculate_true_laspeyres_index(
            CURRENT_QUANTITIES, BASE_QUANTITIES, BASE_PRICES
        ),
        calculate_paasche_index(CURRENT_QUANTITIES, BASE_QUANTITIES, CURRENT_PRICES),
    )
    product = (price_fisher / 100.0) * (quantity_fisher / 100.0)
    assert product == pytest.approx(_value_ratio(), rel=1e-12)


def test_engine_laspeyres_with_quantities_satisfies_fisher_factor_reversal() -> None:
    """Passing base_quantities to calculate_laspeyres_index activates True Laspeyres and passes factor reversal."""
    price_fisher = calculate_fisher_index(
        calculate_laspeyres_index(
            CURRENT_PRICES, BASE_PRICES, base_quantities=BASE_QUANTITIES
        ),
        calculate_paasche_index(CURRENT_PRICES, BASE_PRICES, CURRENT_QUANTITIES),
    )
    quantity_fisher = calculate_fisher_index(
        calculate_laspeyres_index(
            CURRENT_QUANTITIES, BASE_QUANTITIES, base_quantities=BASE_PRICES
        ),
        calculate_paasche_index(CURRENT_QUANTITIES, BASE_QUANTITIES, CURRENT_PRICES),
    )
    product = (price_fisher / 100.0) * (quantity_fisher / 100.0)
    assert product == pytest.approx(_value_ratio(), rel=1e-12)
