"""Weights of Evidence (WofE) prospectivity modelling on numpy grids.

Classic Agterberg/Bonham-Carter formulation:
  W+ = ln( P(B|D) / P(B|~D) ),  W- = ln( P(~B|D) / P(~B|~D) )
for each binary evidence layer B against training deposits D. Posterior
log-odds = prior log-odds + sum of W+/W- per cell; posterior probability
via inverse logit.

This is a deliberately lightweight implementation for screening. For
production, swap in eis_toolkit (Horizon EU) which provides validated WofE,
RF and CNN methods with the same layer inputs.
"""

from __future__ import annotations

import numpy as np


def _binarize(layer: np.ndarray, threshold: float, direction: str = ">=") -> np.ndarray:
    if direction == ">=":
        return layer >= threshold
    return layer <= threshold


def weights_for_layer(evidence: np.ndarray, deposits: np.ndarray) -> tuple[float, float]:
    """Compute (W+, W-) for a boolean evidence grid vs boolean deposit grid.

    Uses a 0.5 continuity correction to avoid log(0) on sparse training sets.
    """
    if evidence.shape != deposits.shape:
        raise ValueError("evidence and deposits grids must have the same shape")
    b, d = evidence.astype(bool), deposits.astype(bool)

    n_bd = np.sum(b & d) + 0.5
    n_b_nd = np.sum(b & ~d) + 0.5
    n_nb_d = np.sum(~b & d) + 0.5
    n_nb_nd = np.sum(~b & ~d) + 0.5
    n_d = n_bd + n_nb_d
    n_nd = n_b_nd + n_nb_nd

    w_plus = float(np.log((n_bd / n_d) / (n_b_nd / n_nd)))
    w_minus = float(np.log((n_nb_d / n_d) / (n_nb_nd / n_nd)))
    return w_plus, w_minus


def posterior_probability(
    layers: dict[str, tuple[np.ndarray, float, str]],
    deposits: np.ndarray,
) -> tuple[np.ndarray, dict[str, tuple[float, float]]]:
    """Run WofE over evidence layers.

    layers: name -> (continuous grid, binarization threshold, direction)
    deposits: boolean grid of training occurrences.
    Returns (posterior probability grid, per-layer (W+, W-) dict).
    """
    n_cells = deposits.size
    n_dep = max(int(deposits.sum()), 1)
    prior_odds = n_dep / (n_cells - n_dep)
    logit = np.full(deposits.shape, np.log(prior_odds), dtype=np.float64)

    weights: dict[str, tuple[float, float]] = {}
    for name, (grid, thr, direction) in layers.items():
        b = _binarize(grid, thr, direction)
        w_plus, w_minus = weights_for_layer(b, deposits)
        weights[name] = (w_plus, w_minus)
        logit += np.where(b, w_plus, w_minus)

    posterior = 1.0 / (1.0 + np.exp(-logit))
    return posterior, weights
