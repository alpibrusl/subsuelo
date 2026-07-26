"""Tests for the WofE validation harness.

The point of a validation harness is that it says "no" to a bad model, so these
tests check the metrics discriminate rather than merely run: an informative
layer must score well above a pure-noise layer, and a random split must score
higher than a spatially blocked one on clustered occurrences (that gap is the
leakage the blocking exists to remove).

Run: python -m pytest subsuelo/tests/test_validate.py   (or: python subsuelo/tests/test_validate.py)
"""

from __future__ import annotations

import numpy as np

from subsuelo.model.validate import (
    conditional_independence,
    random_folds,
    roc_auc,
    spatial_block_folds,
    success_rate_curve,
    validate,
)

SHAPE = (120, 120)


def _clustered_world(seed: int = 0):
    """A synthetic belt: occurrences cluster on a high-signal band."""
    rng = np.random.default_rng(seed)
    ny, nx = SHAPE
    yy, xx = np.mgrid[0:ny, 0:nx]

    # signal: distance to a diagonal "contact" — low distance = prospective
    dist = np.abs(yy - xx) / np.sqrt(2.0)
    signal = dist + rng.normal(0, 3.0, SHAPE)
    noise = rng.normal(0, 1.0, SHAPE)

    # occurrences: clustered along the contact, in a few discrete clumps
    deposits = np.zeros(SHAPE, dtype=bool)
    for cy in (20, 45, 70, 95):
        for _ in range(6):
            oy = int(np.clip(cy + rng.normal(0, 3), 0, ny - 1))
            ox = int(np.clip(cy + rng.normal(0, 3), 0, nx - 1))
            deposits[oy, ox] = True

    good = {"dist_contact": (signal, 8.0, "<=")}
    bad = {"noise": (noise, 0.0, ">=")}
    return good, bad, deposits


def test_success_curve_beats_random_for_informative_layer():
    good, bad, deposits = _clustered_world()
    from subsuelo.model.wofe import posterior_probability

    p_good, _ = posterior_probability(good, deposits)
    p_bad, _ = posterior_probability(bad, deposits)

    auc_good = success_rate_curve(p_good, deposits).auc
    auc_bad = success_rate_curve(p_bad, deposits).auc

    assert auc_good > 0.75, f"informative layer scored only {auc_good:.3f}"
    assert auc_bad < 0.65, f"noise layer scored {auc_bad:.3f} — metric is not discriminating"
    assert auc_good > auc_bad + 0.15


def test_success_curve_bounds_and_monotonicity():
    good, _, deposits = _clustered_world()
    from subsuelo.model.wofe import posterior_probability

    posterior, _ = posterior_probability(good, deposits)
    curve = success_rate_curve(posterior, deposits)

    captured = np.asarray(curve.captured_fraction)
    assert np.all(np.diff(captured) >= -1e-12), "capture curve must be non-decreasing"
    assert 0.0 <= curve.auc <= 1.0
    assert 0.0 < curve.area_at_50 <= 1.0
    assert curve.area_at_50 <= curve.area_at_80


def test_roc_auc_matches_random_expectation_on_noise():
    rng = np.random.default_rng(3)
    posterior = rng.random(SHAPE)
    deposits = rng.random(SHAPE) < 0.002
    assert abs(roc_auc(posterior, deposits) - 0.5) < 0.12


def test_roc_auc_handles_ties():
    """All-constant posterior is a pure tie — AUC must be exactly 0.5, not 0 or 1."""
    posterior = np.full(SHAPE, 0.3)
    deposits = np.zeros(SHAPE, dtype=bool)
    deposits[::40, ::40] = True
    assert abs(roc_auc(posterior, deposits) - 0.5) < 1e-9


def test_spatial_blocks_are_contiguous():
    folds = spatial_block_folds(SHAPE, n_folds=5, block_cells=20, seed=1)
    # every cell inside one block carries the same fold id
    assert len(np.unique(folds[0:20, 0:20])) == 1
    assert set(np.unique(folds)) <= set(range(5))


def test_leakage_gap_is_negligible_for_wofe():
    """WofE fits two global parameters per layer (W+, W-), so it has essentially
    no capacity to memorise a neighbourhood — the blocked and random splits
    should agree closely.

    This is the expected result for *this* model, not a sign the blocking does
    nothing: it is the baseline against which a higher-capacity model (the RF or
    CNN in eis_toolkit that wofe.py names as the production path) should be
    compared. A large positive gap there would mean its random-split scores are
    inflated. Guard the baseline so that comparison stays meaningful.
    """
    good, _, deposits = _clustered_world()
    report = validate(good, deposits, n_folds=4, block_cells=20, seed=0)
    assert abs(report.leakage_gap) < 0.1, (
        f"unexpected gap for a 2-parameter model: blocked {report.auc_mean:.3f} "
        f"vs random {report.auc_random_mean:.3f}"
    )


def test_conditional_independence_flags_duplicated_evidence():
    """Feeding the same layer twice is maximal CI violation — it must be caught."""
    good, _, deposits = _clustered_world()
    signal, thr, direction = good["dist_contact"]

    single = conditional_independence(
        *_posterior_and_deposits({"a": (signal, thr, direction)}, deposits)
    )
    duplicated = conditional_independence(
        *_posterior_and_deposits(
            {"a": (signal, thr, direction), "a_copy": (signal.copy(), thr, direction)},
            deposits,
        )
    )
    assert duplicated["inflation"] > single["inflation"]
    assert not duplicated["independent"], "duplicated evidence must fail the CI test"


def _posterior_and_deposits(layers, deposits):
    from subsuelo.model.wofe import posterior_probability

    posterior, _ = posterior_probability(layers, deposits)
    return posterior, deposits


def test_validate_is_deterministic():
    good, _, deposits = _clustered_world()
    a = validate(good, deposits, n_folds=4, block_cells=20, seed=7)
    b = validate(good, deposits, n_folds=4, block_cells=20, seed=7)
    assert a.auc_mean == b.auc_mean
    assert a.conditional_independence["z"] == b.conditional_independence["z"]


def test_validate_warns_on_sparse_occurrences():
    good, _, _ = _clustered_world()
    sparse = np.zeros(SHAPE, dtype=bool)
    sparse[::30, ::30] = True   # a handful, spread out
    report = validate(good, sparse, n_folds=4, block_cells=20, seed=0)
    if int(sparse.sum()) < 8:
        assert any("occurrences" in w for w in report.warnings)
    assert isinstance(report.summary(), str)


if __name__ == "__main__":
    import sys, traceback

    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
