"""Censoring-aware scoring for fixed-horizon event probabilities.

All metrics use inverse probability of censoring weights (IPCW, Graf et al.
1999): an event before the horizon is weighted 1/G(T-), a subject still
event-free at the horizon 1/G(horizon), and a subject censored before the
horizon gets weight 0. G is the Kaplan-Meier estimate of the censoring
distribution, fitted on the evaluated sample.

Optional design weights (``dw``, the inverse probability that a decision point
was selected for evaluation) multiply every case's weight, enter the
censoring Kaplan-Meier, and normalise the Brier score and log loss.
"""
from __future__ import annotations

import numpy as np

EPS = 1e-12


def km_censoring(t: np.ndarray, e: np.ndarray, w: np.ndarray | None = None):
    """(Weighted) Kaplan-Meier of the censoring distribution. Returns (times, survival) step arrays."""
    t = np.asarray(t, float)
    c = 1 - np.asarray(e, int)  # censoring indicator
    w = np.ones(len(t)) if w is None else np.asarray(w, float)
    order = np.argsort(t, kind="stable")
    t, c, w = t[order], c[order], w[order]
    uniq = np.unique(t)
    cum = np.r_[0.0, np.cumsum(w)]
    at_risk = cum[-1] - cum[np.searchsorted(t, uniq, side="left")]
    # censorings at each unique time; subjects with an event at that time stay in the risk set
    cens = _count_at(t, c * w, uniq)
    surv = np.cumprod(1.0 - cens / np.maximum(at_risk, 1e-12))
    return uniq, surv


def _count_at(t, c, uniq):
    idx = np.searchsorted(uniq, t)
    return np.bincount(idx, weights=c, minlength=len(uniq))


def _G(times, surv, x, left: bool):
    """Evaluate the step function at x (left limit if left=True)."""
    side = "left" if left else "right"
    i = np.searchsorted(times, x, side=side) - 1
    out = np.where(i >= 0, surv[np.clip(i, 0, len(surv) - 1)], 1.0)
    return np.maximum(out, 1e-3)


def ipcw_weights(t, e, horizon, dw=None):
    """Status (1 event by horizon, 0 event-free at horizon, -1 censored) and weights (× design weights)."""
    t = np.asarray(t, float)
    e = np.asarray(e, int)
    dw = np.ones(len(t)) if dw is None else np.asarray(dw, float)
    status = np.full(len(t), -1, int)
    status[(e == 1) & (t <= horizon)] = 1
    status[t > horizon] = 0
    times, surv = km_censoring(t, e, dw)
    w = np.zeros(len(t))
    m1 = status == 1
    w[m1] = 1.0 / _G(times, surv, t[m1], left=True)
    m0 = status == 0
    w[m0] = 1.0 / _G(times, surv, np.full(m0.sum(), horizon), left=False)
    return status, w * dw


def km_event_prob(t, e, horizon, weights=None) -> float:
    """1 - Kaplan-Meier survival at the horizon (marginal event probability).

    Optional case weights (e.g. 1 / decision points per patient) give a
    weighted Kaplan-Meier estimate.
    """
    t = np.asarray(t, float)
    w = np.ones(len(t)) if weights is None else np.asarray(weights, float)
    return _km_event(t, np.asarray(e, int), horizon, w)


def _km_event(t, e, horizon, w):
    order = np.argsort(t, kind="stable")
    t, e, w = t[order], e[order], w[order]
    ev = (e == 1) & (t <= horizon)
    if not ev.any():
        return 0.0
    uniq = np.unique(t[ev])
    cum = np.r_[0.0, np.cumsum(w)]
    at_risk = cum[-1] - cum[np.searchsorted(t, uniq, side="left")]
    d = np.bincount(np.searchsorted(uniq, t[ev]), weights=w[ev], minlength=len(uniq))
    return float(1 - np.prod(1 - d / np.maximum(at_risk, 1e-12)))


def brier(p, status, w, norm=None):
    y = (status == 1).astype(float)
    return float(np.sum(w * (y - p) ** 2) / (len(p) if norm is None else norm))


def log_loss(p, status, w, clip=0.01, norm=None):
    p = np.clip(p, clip, 1 - clip)
    y = (status == 1).astype(float)
    m = status >= 0
    return float(-np.sum(w[m] * (y[m] * np.log(p[m]) + (1 - y[m]) * np.log(1 - p[m])))
                 / (len(p) if norm is None else norm))


def weighted_auc(p, status, w):
    m = status >= 0
    p, y, w = p[m], (status[m] == 1), w[m]
    if y.sum() == 0 or (~y).sum() == 0:
        return float("nan")
    order = np.argsort(p, kind="stable")
    p, y, w = p[order], y[order], w[order]
    wn_total = w[~y].sum()
    wp_total = w[y].sum()
    acc = 0.0
    neg_below = 0.0
    i = 0
    n = len(p)
    while i < n:
        j = i
        while j < n and p[j] == p[i]:
            j += 1
        wp = w[i:j][y[i:j]].sum()
        wn = w[i:j][~y[i:j]].sum()
        acc += wp * (neg_below + 0.5 * wn)
        neg_below += wn
        i = j
    return float(acc / (wp_total * wn_total))


def _logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def _wlogreg(x, y, w, offset=None, fit_slope=True, iters=100):
    """Weighted logistic regression y ~ a + b*x (+ offset) by damped Newton.

    Each Newton step is halved until the weighted log-likelihood improves, so the
    fit converges for overconfident or uninformative predictions too. Returns
    (a, b, converged).
    """
    x = np.asarray(x, float)
    off = np.zeros_like(x) if offset is None else np.asarray(offset, float)
    X = np.column_stack([np.ones_like(x), x]) if fit_slope else np.ones((len(x), 1))
    theta = np.array([0.0, 1.0]) if fit_slope else np.array([0.0])

    def nll(th):
        eta = X @ th + off
        return float(np.sum(w * (np.logaddexp(0.0, eta) - y * eta)))

    f = nll(theta)
    converged = False
    for _ in range(iters):
        eta = X @ theta + off
        mu = 0.5 * (1.0 + np.tanh(0.5 * eta))      # stable sigmoid
        grad = X.T @ (w * (y - mu))
        H = (X * (w * mu * (1 - mu))[:, None]).T @ X + 1e-10 * np.eye(X.shape[1])
        try:
            step = np.linalg.solve(H, grad)
        except np.linalg.LinAlgError:
            break
        t = 1.0
        while t > 1e-10:
            cand = theta + t * step
            fc = nll(cand)
            if fc <= f + 1e-12 * max(1.0, abs(f)):
                break
            t *= 0.5
        else:
            break
        theta, f_old, f = cand, f, fc
        if np.max(np.abs(t * step)) < 1e-9 or abs(f_old - f) < 1e-12 * max(1.0, abs(f)):
            converged = True
            break
    a = float(theta[0])
    b = float(theta[1]) if fit_slope else 0.0
    return a, b, converged


def calibration(p, status, w):
    m = status >= 0
    x = _logit(p[m])
    y = (status[m] == 1).astype(float)
    ww = w[m]
    if len(np.unique(y)) < 2:
        return {"slope": float("nan"), "intercept": float("nan")}
    a0, _, ok0 = _wlogreg(np.zeros_like(x), y, ww, offset=x, fit_slope=False)
    intercept = float(a0) if ok0 else float("nan")
    if np.ptp(x) < 1e-9:  # constant predictions: no slope to fit
        return {"slope": float("nan"), "intercept": intercept}
    a, b, ok = _wlogreg(x, y, ww)
    return {"slope": float(b) if ok else float("nan"), "intercept": intercept}


def ece(p, status, w, bins=10):
    m = status >= 0
    p, y, w = p[m], (status[m] == 1).astype(float), w[m]
    if w.sum() == 0:
        return float("nan")
    idx = np.minimum((p * bins).astype(int), bins - 1)
    tot = 0.0
    for b in range(bins):
        k = idx == b
        if k.any() and w[k].sum() > 0:
            tot += w[k].sum() * abs(np.average(y[k], weights=w[k]) - np.average(p[k], weights=w[k]))
    return float(tot / w.sum())


def reliability(p, status, w, bins=10):
    m = status >= 0
    p, y, w = p[m], (status[m] == 1).astype(float), w[m]
    idx = np.minimum((p * bins).astype(int), bins - 1)
    out = []
    for b in range(bins):
        k = idx == b
        if k.any() and w[k].sum() > 0:
            out.append({"bin": b, "n": int(k.sum()), "mean_pred": float(np.average(p[k], weights=w[k])),
                        "observed": float(np.average(y[k], weights=w[k]))})
    return out


def all_metrics(p, t, e, horizon, p_ref=None, dw=None) -> dict:
    p = np.clip(np.asarray(p, float), 0.0, 1.0)
    dw = np.ones(len(p)) if dw is None else np.asarray(dw, float)
    status, w = ipcw_weights(t, e, horizon, dw)
    norm = float(dw.sum())
    bs = brier(p, status, w, norm)
    marginal = km_event_prob(t, e, horizon, dw)
    bs_marg = brier(np.full(len(p), marginal), status, w, norm)
    cc = status >= 0
    out = {
        "n": int(len(p)),
        "n_censored_before_horizon": int((status == -1).sum()),
        "event_rate_km": float(marginal),
        "mean_pred": float(np.average(p, weights=dw)),
        "brier": bs,
        "bss_vs_marginal": float(1 - bs / bs_marg) if bs_marg > 0 else float("nan"),
        "log_loss": log_loss(p, status, w, norm=norm),
        "auroc": weighted_auc(p, status, w),
        "ece": ece(p, status, w),
        **{f"calibration_{k}": v for k, v in calibration(p, status, w).items()},
        # sensitivity check: drop cases censored before the horizon, no censoring weights
        "brier_complete_case": float(np.average(((status[cc] == 1) - p[cc]) ** 2, weights=dw[cc]))
        if cc.any() else float("nan"),
    }
    if p_ref is not None:
        bs_ref = brier(np.clip(np.asarray(p_ref, float), 0, 1), status, w, norm)
        out["brier_ref"] = bs_ref
        out["bss_vs_ref"] = float(1 - bs / bs_ref) if bs_ref > 0 else float("nan")
    return out


def bootstrap(p, t, e, horizon, clusters=None, p_ref=None, n_boot=2000, seed=0,
              keys=("brier", "bss_vs_marginal", "bss_vs_ref", "auroc", "calibration_slope", "ece"),
              dw=None) -> dict:
    """Percentile 95% intervals from a cluster (patient-level) bootstrap."""
    p = np.asarray(p, float)
    t = np.asarray(t, float)
    e = np.asarray(e, int)
    n = len(p)
    dw = np.ones(n) if dw is None else np.asarray(dw, float)
    rng = np.random.default_rng(seed)
    if clusters is None:
        groups = [np.array([i]) for i in range(n)]
    else:
        clusters = np.asarray(clusters)
        _, inv = np.unique(clusters, return_inverse=True)
        groups = [np.flatnonzero(inv == g) for g in range(inv.max() + 1)]
    vals = {k: [] for k in keys}
    for _ in range(n_boot):
        pick = rng.integers(0, len(groups), len(groups))
        idx = np.concatenate([groups[g] for g in pick])
        m = all_metrics(p[idx], t[idx], e[idx], horizon, None if p_ref is None else np.asarray(p_ref)[idx], dw[idx])
        for k in keys:
            if k in m:
                vals[k].append(m[k])
    out = {}
    for k, v in vals.items():
        v = np.array([x for x in v if np.isfinite(x)])
        if len(v):
            out[k] = [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
    return out
