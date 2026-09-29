"""Small, auditable regression solvers for CPU research, never runtime routing."""
import itertools
import numpy as np


def nnls_small(x, y):
    """Enumerate every active face (at most three columns), including zero.

    Refit each face; clipping an unconstrained fit does not solve NNLS.
    Column scaling changes coordinates, not the objective being minimized.
    """
    x, y = np.asarray(x, float), np.asarray(y, float)
    if (x.ndim != 2 or y.shape != (len(x),) or not len(x) or
            not 1 <= x.shape[1] <= 3 or not np.isfinite(x).all() or not np.isfinite(y).all()):
        raise ValueError('Expected finite N-by-[1,3] design and N response')
    scale = np.maximum(np.sqrt(np.mean(x*x, axis=0)), 1e-30)
    xn = x/scale
    best = np.zeros(x.shape[1]); loss = float(y@y)
    for count in range(1, x.shape[1]+1):
        for indices in itertools.combinations(range(x.shape[1]), count):
            columns = list(indices)
            k = np.linalg.lstsq(xn[:, columns], y, rcond=1e-12)[0]
            tolerance = 64*np.finfo(float).eps*max(1., np.linalg.norm(k))
            if np.any(k < -tolerance):
                continue
            candidate = np.zeros_like(best)
            candidate[columns] = np.maximum(k, 0)/scale[columns]
            residual = y-x@candidate
            objective = float(residual@residual)
            if objective < loss:
                best, loss = candidate, objective
    return best


def applied_fit(x, y, validation, target):
    """Validate exactly the constrained model subsequently used for prediction.

    Keep the full-design covariance using the constrained residual variance.
    A boundary coefficient is not known exactly: zeroing its covariance would
    falsely make a boundary share appear certain. This is a conservative local
    approximation, not a calibrated confidence interval for constrained fits.
    """
    coef = nnls_small(x, y)
    residual = y-x@coef
    mse = float(np.mean(residual*residual))
    scale = np.maximum(np.sqrt(np.mean(x*x, axis=0)), 1e-30)
    xn = x/scale
    covariance = np.linalg.pinv(xn.T@xn, rcond=1e-12)*mse
    covariance /= scale[:, None]*scale[None, :]
    return coef, covariance, np.sqrt(mse), float(np.sqrt(np.mean((target-validation@coef)**2)))
