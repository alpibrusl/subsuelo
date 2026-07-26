"""Validation for WofE prospectivity models.

An unvalidated prospectivity map is unfalsifiable: every cell gets a number,
the high ones look plausible, and nothing tells you whether the ranking beats
drawing circles at random. This module supplies the evidence.

What it measures
----------------
**Success-rate / prediction-rate curve** — the standard metric in mineral
prospectivity mapping. Rank every cell by posterior, walk down the ranking, and
plot the fraction of known occurrences captured against the fraction of area
consumed. A useful model captures most occurrences in a small slice of ground;
the area under that curve (`auc`) is 0.5 for a coin flip and 1.0 for perfect.
Fitted on training occurrences and scored on *held-out* ones, this is a
prediction-rate curve — the honest version.

**Spatially blocked cross-validation** — occurrences cluster (that is what an
ore belt *is*). A random train/test split can therefore leak: a test
occurrence's neighbours sit in the training set, and a model with local capacity
scores well by memorising the neighbourhood rather than learning the geology.
Splitting by contiguous spatial blocks keeps that neighbourhood out of training.
Both splits are computed and `leakage_gap` reports the difference.

A caveat worth stating plainly, because it changes how you read the number:
**plain WofE has two free parameters per layer** (W+ and W-), estimated
globally, so it has almost no capacity to memorise anything spatial — and the
measured gap on this model is near zero. That is the correct result, not a
broken harness. The blocked split matters much more the moment a higher-capacity
model goes in (the random forest or CNN in eis_toolkit, which `wofe.py` already
names as the production path); the harness is here so that swap can be measured
rather than assumed. Until then, treat a large gap as a red flag and a small one
as expected.

**Conditional-independence test** — WofE's known weak point. The method assumes
evidence layers are conditionally independent given the deposits, and real
geological layers rarely are (distance-to-granite and distance-to-contact
measure overlapping things). Violating it inflates posteriors while leaving the
*ranking* largely intact — which is why a model can be badly miscalibrated and
still look fine on a success-rate curve. The Agterberg–Cheng omnibus test
compares the summed posterior over the study area against the observed
occurrence count: under conditional independence they should agree.

Interpreting the numbers
------------------------
- `auc` (blocked, held-out) is the headline. Below ~0.65 the model is weak;
  0.75+ is respectable for regional screening on open data.
- `leakage_gap` (random minus blocked) is the leakage estimate. Expect ≈0 for
  plain WofE; a large positive gap on a higher-capacity model means its
  random-split numbers are optimistic and should not be published.
- `ci_z` well above ~1.96 means posteriors are inflated; treat them as a
  *ranking*, not as probabilities, and say so in the UI.

Everything here is deterministic given `seed`, uses only numpy/scipy, and makes
no network calls — it runs offline against a cached build.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field

import numpy as np
from scipy.stats import norm

from .wofe import posterior_probability

__all__ = [
    "SuccessCurve",
    "FoldResult",
    "ValidationReport",
    "success_rate_curve",
    "roc_auc",
    "spatial_block_folds",
    "random_folds",
    "conditional_independence",
    "cross_validate",
    "validate",
]


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------

@dataclass
class SuccessCurve:
    """Cumulative occurrences captured vs cumulative area consumed."""

    area_fraction: list[float]
    captured_fraction: list[float]
    auc: float
    #: area fraction needed to capture 50% / 80% of held-out occurrences
    area_at_50: float
    area_at_80: float

    def as_dict(self) -> dict:
        return asdict(self)


def success_rate_curve(
    posterior: np.ndarray,
    deposits: np.ndarray,
    n_points: int = 200,
) -> SuccessCurve:
    """Rank cells by posterior and measure occurrence capture against area.

    `deposits` should be the *held-out* occurrences when the posterior was fitted
    elsewhere — that makes this a prediction-rate curve. Passing the training
    occurrences yields a success-rate curve, which will be optimistic.
    """
    p = np.asarray(posterior, dtype=np.float64).ravel()
    d = np.asarray(deposits).astype(bool).ravel()
    if p.shape != d.shape:
        raise ValueError("posterior and deposits must have the same shape")
    n_dep = int(d.sum())
    if n_dep == 0:
        raise ValueError("no occurrences to validate against")

    # Descending by posterior. Ties are broken deterministically by index so the
    # curve is reproducible; with many tied cells this is pessimistic, which is
    # the direction we want to err in.
    order = np.argsort(-p, kind="stable")
    captured = np.cumsum(d[order]) / n_dep
    area = np.arange(1, p.size + 1, dtype=np.float64) / p.size

    auc = float(np.trapezoid(captured, area)) if hasattr(np, "trapezoid") \
        else float(np.trapz(captured, area))

    def _area_at(target: float) -> float:
        idx = int(np.searchsorted(captured, target, side="left"))
        return float(area[min(idx, area.size - 1)])

    # Downsample for storage/plotting without distorting the AUC.
    step = max(1, p.size // n_points)
    return SuccessCurve(
        area_fraction=[float(x) for x in area[::step]],
        captured_fraction=[float(x) for x in captured[::step]],
        auc=auc,
        area_at_50=_area_at(0.5),
        area_at_80=_area_at(0.8),
    )


def roc_auc(posterior: np.ndarray, deposits: np.ndarray) -> float:
    """ROC AUC via the rank (Mann–Whitney U) identity — no sklearn needed.

    Reported alongside the success-rate AUC because it is the number most
    reviewers recognise, but the success-rate curve is the more informative one
    here: it answers "how much ground must I cover", which is the actual
    screening question.
    """
    p = np.asarray(posterior, dtype=np.float64).ravel()
    d = np.asarray(deposits).astype(bool).ravel()
    n_pos = int(d.sum())
    n_neg = int(d.size - n_pos)
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    # average ranks handle ties correctly
    order = np.argsort(p, kind="stable")
    ranks = np.empty(p.size, dtype=np.float64)
    ranks[order] = np.arange(1, p.size + 1, dtype=np.float64)
    _, inv, counts = np.unique(p, return_inverse=True, return_counts=True)
    sums = np.zeros(counts.size, dtype=np.float64)
    np.add.at(sums, inv, ranks)
    ranks = (sums / counts)[inv]
    return float((ranks[d].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


# --------------------------------------------------------------------------
# splits
# --------------------------------------------------------------------------

def spatial_block_folds(
    shape: tuple[int, int],
    n_folds: int = 5,
    block_cells: int = 25,
    seed: int = 0,
) -> np.ndarray:
    """Assign every cell to one of `n_folds` via contiguous spatial blocks.

    Occurrences in an ore belt are clustered, so a random cell-wise split puts a
    test occurrence's immediate neighbours into training and the model scores
    well for the wrong reason. Blocking at `block_cells` × `block_cells` keeps a
    neighbourhood together; the block should be at least as large as the spatial
    correlation length of the evidence (for distance-to-feature layers, a few
    kilometres — with 250 m cells, 25 cells ≈ 6 km).
    """
    ny, nx = shape
    by = (np.arange(ny) // block_cells)[:, None]
    bx = (np.arange(nx) // block_cells)[None, :]
    n_by, n_bx = int(by.max()) + 1, int(bx.max()) + 1
    block_id = (by * n_bx + bx).astype(np.int64)

    rng = np.random.default_rng(seed)
    assignment = rng.permutation(n_by * n_bx) % n_folds
    return assignment[block_id]


def random_folds(shape: tuple[int, int], n_folds: int = 5, seed: int = 0) -> np.ndarray:
    """Cell-wise random folds. Provided for comparison only — the gap against
    `spatial_block_folds` is the leakage estimate, not a score to report."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, n_folds, size=shape)


# --------------------------------------------------------------------------
# conditional independence (Agterberg–Cheng omnibus)
# --------------------------------------------------------------------------

def conditional_independence(posterior: np.ndarray, deposits: np.ndarray) -> dict:
    """Agterberg–Cheng omnibus test for the WofE conditional-independence assumption.

    Under conditional independence the posterior summed over every cell equals
    the observed number of occurrences. Correlated evidence layers double-count
    the same signal, so the sum runs high.

    Returns `t` (summed posterior), `n` (observed), `z`, `p_value`, and
    `inflation` = t / n. A one-sided p below 0.05 means the assumption is
    rejected: the posteriors are inflated and should be presented as a relative
    ranking rather than as probabilities.
    """
    p = np.asarray(posterior, dtype=np.float64).ravel()
    n_obs = float(np.asarray(deposits).astype(bool).sum())
    t = float(p.sum())
    var = float(np.sum(p * (1.0 - p)))
    z = (t - n_obs) / np.sqrt(var) if var > 0 else float("nan")
    return {
        "t_sum_posterior": t,
        "n_observed": n_obs,
        "z": float(z),
        "p_value": float(1.0 - norm.cdf(z)) if np.isfinite(z) else float("nan"),
        "inflation": float(t / n_obs) if n_obs > 0 else float("nan"),
        "independent": bool(np.isfinite(z) and z < 1.96),
    }


# --------------------------------------------------------------------------
# cross-validation
# --------------------------------------------------------------------------

@dataclass
class FoldResult:
    fold: int
    n_train: int
    n_test: int
    auc: float
    roc_auc: float
    area_at_50: float
    area_at_80: float


@dataclass
class ValidationReport:
    n_occurrences: int
    n_cells: int
    n_folds: int
    block_cells: int
    seed: int
    #: blocked CV — the honest headline number
    auc_mean: float
    auc_std: float
    roc_auc_mean: float
    area_at_50_mean: float
    area_at_80_mean: float
    #: cell-wise random CV, for the leakage comparison only
    auc_random_mean: float
    leakage_gap: float
    #: full-fit diagnostics
    conditional_independence: dict
    curve: SuccessCurve
    folds: list[FoldResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["curve"] = self.curve.as_dict()
        return d

    def summary(self) -> str:
        ci = self.conditional_independence
        lines = [
            f"occurrences: {self.n_occurrences}   cells: {self.n_cells}",
            f"blocked {self.n_folds}-fold AUC : {self.auc_mean:.3f} ± {self.auc_std:.3f}",
            f"random  {self.n_folds}-fold AUC : {self.auc_random_mean:.3f}"
            f"   (leakage gap {self.leakage_gap:+.3f})",
            f"ROC AUC                : {self.roc_auc_mean:.3f}",
            f"area for 50% capture   : {self.area_at_50_mean * 100:.1f}%",
            f"area for 80% capture   : {self.area_at_80_mean * 100:.1f}%",
            f"cond. independence     : z={ci['z']:.2f} p={ci['p_value']:.4f}"
            f" inflation={ci['inflation']:.2f}"
            f" ({'ok' if ci['independent'] else 'REJECTED — posteriors inflated'})",
        ]
        for w in self.warnings:
            lines.append(f"warning: {w}")
        return "\n".join(lines)


def _fit_and_score(layers, deposits, train_mask, test_dep) -> tuple[float, float, float, float]:
    train_dep = deposits & train_mask
    posterior, _ = posterior_probability(layers, train_dep)
    # score only where we did not train, so the curve cannot see training ground
    hold = ~train_mask
    curve = success_rate_curve(posterior[hold], test_dep[hold])
    return curve.auc, roc_auc(posterior[hold], test_dep[hold]), curve.area_at_50, curve.area_at_80


def cross_validate(
    layers: dict[str, tuple[np.ndarray, float, str]],
    deposits: np.ndarray,
    n_folds: int = 5,
    block_cells: int = 25,
    seed: int = 0,
    folds: np.ndarray | None = None,
) -> list[FoldResult]:
    """Fit on k-1 folds, score held-out occurrences on the remaining one."""
    deposits = np.asarray(deposits).astype(bool)
    if folds is None:
        folds = spatial_block_folds(deposits.shape, n_folds, block_cells, seed)

    results: list[FoldResult] = []
    for k in range(n_folds):
        train_mask = folds != k
        test_dep = deposits & ~train_mask
        n_test = int(test_dep.sum())
        n_train = int((deposits & train_mask).sum())
        if n_test == 0 or n_train == 0:
            continue
        auc, rauc, a50, a80 = _fit_and_score(layers, deposits, train_mask, test_dep)
        results.append(FoldResult(k, n_train, n_test, auc, rauc, a50, a80))
    return results


def validate(
    layers: dict[str, tuple[np.ndarray, float, str]],
    deposits: np.ndarray,
    n_folds: int = 5,
    block_cells: int = 25,
    seed: int = 0,
) -> ValidationReport:
    """Full harness: blocked CV, a random-split comparison, and the CI test."""
    deposits = np.asarray(deposits).astype(bool)
    n_occ = int(deposits.sum())
    warnings: list[str] = []

    if n_occ < 8:
        warnings.append(
            f"only {n_occ} occurrences — cross-validated scores are indicative at best"
        )
    if n_occ < n_folds:
        raise ValueError(f"{n_occ} occurrences cannot fill {n_folds} folds")

    blocked = cross_validate(layers, deposits, n_folds, block_cells, seed)
    if not blocked:
        raise ValueError("no usable folds — occurrences may sit inside one block")
    if len(blocked) < n_folds:
        warnings.append(
            f"{n_folds - len(blocked)} of {n_folds} folds held no occurrences and were skipped"
        )

    rnd = cross_validate(
        layers, deposits, n_folds, block_cells, seed,
        folds=random_folds(deposits.shape, n_folds, seed),
    )

    aucs = np.array([f.auc for f in blocked], dtype=np.float64)
    auc_rand = float(np.mean([f.auc for f in rnd])) if rnd else float("nan")

    # full fit, for the CI test and the reported curve
    posterior, _ = posterior_probability(layers, deposits)
    ci = conditional_independence(posterior, deposits)
    if not ci["independent"]:
        warnings.append(
            f"conditional independence rejected (inflation {ci['inflation']:.2f}×) — "
            "present posteriors as a ranking, not as probabilities"
        )

    report = ValidationReport(
        n_occurrences=n_occ,
        n_cells=int(deposits.size),
        n_folds=n_folds,
        block_cells=block_cells,
        seed=seed,
        auc_mean=float(aucs.mean()),
        auc_std=float(aucs.std()),
        roc_auc_mean=float(np.mean([f.roc_auc for f in blocked])),
        area_at_50_mean=float(np.mean([f.area_at_50 for f in blocked])),
        area_at_80_mean=float(np.mean([f.area_at_80 for f in blocked])),
        auc_random_mean=auc_rand,
        leakage_gap=float(auc_rand - aucs.mean()) if np.isfinite(auc_rand) else float("nan"),
        conditional_independence=ci,
        curve=success_rate_curve(posterior, deposits),
        folds=blocked,
        warnings=warnings,
    )
    if report.auc_mean < 0.65:
        report.warnings.append(
            f"blocked AUC {report.auc_mean:.3f} is weak — the ranking is barely "
            "better than area-proportional guessing"
        )
    return report


def write_report(report: ValidationReport, path: str) -> None:
    """Dump the report as JSON next to the build artifacts."""
    with open(path, "w") as f:
        json.dump(report.as_dict(), f, indent=2)
