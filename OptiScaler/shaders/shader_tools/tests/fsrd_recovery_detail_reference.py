"""Floor-free causal moments of paired RR-input minus RR-output detail.

This is an offline reference, not an enabled production recovery.  Every
observation comes from the same lobe and frame.  Neither Floor nor Skip color
is a witness.  The gate remains separate from the measured signed mean.
"""
from dataclasses import dataclass
import numpy as np


def warp(array, taps):
    result = np.zeros_like(array, dtype=np.float32)
    tail = (None,) * (array.ndim - 2)
    for y, x, weight in taps:
        result += array[y, x] * weight[(...,) + tail]
    return result


@dataclass
class PairedBandMoments:
    shape: tuple
    bands: int
    response: float = .03

    def __post_init__(self):
        if not 0 < self.response <= 1:
            raise ValueError("Response must lie in (0,1]")
        h, w = self.shape
        self.mean = np.zeros((self.bands, h, w, 3), np.float32)
        self.variance = np.zeros_like(self.mean)
        self.mass = np.zeros((h, w), np.float32)
        self.q = np.ones((h, w), np.float32)
        self.age = np.zeros((h, w), np.float32)

    def update(self, observations, taps, reuse):
        observations = np.asarray(observations, np.float32)
        if observations.shape != self.mean.shape:
            raise ValueError("Band observation extent mismatch")
        finite = np.all(np.isfinite(observations), axis=(0, 3))
        reuse = np.asarray(reuse, bool) & finite
        # Startup-normalized EMA. A restart stores the observation as data but
        # it cannot authorize a correction until an independent population exists.
        mass = np.where(reuse, (1-self.response)*warp(self.mass, taps)+self.response,
                        self.response).astype(np.float32)
        a = (self.response/mass).astype(np.float32)
        av = a[..., None]
        for index, observed in enumerate(observations):
            observed = np.where(finite[..., None], observed, 0)
            previous = warp(self.mean[index], taps)
            # Fully correlated bound for a deterministic bilinear gather. A
            # signal gradient between taps is not a random signal choice.
            previous_variance = warp(np.sqrt(np.maximum(self.variance[index], 0)), taps)**2
            delta = observed-previous
            self.mean[index] = np.where(reuse[..., None], previous+av*delta, observed)
            self.variance[index] = np.where(reuse[..., None],
                (1-av)*(previous_variance+av*delta**2), 0)
        self.age = np.where(reuse, warp(self.age, taps)+1, 1).astype(np.float32)
        # Bilinear contributors are correlated histories, not four fresh samples.
        self.q = np.where(reuse, (1-a)**2*warp(self.q, taps)+a**2, 1).astype(np.float32)
        self.mass = mass
        sem2 = self.variance*self.q[None, ..., None]/np.maximum(1-self.q[None, ..., None], 1e-6)
        return self.mean, np.sqrt(np.maximum(sem2, 0))

    @property
    def effective_count(self):
        return 1/np.maximum(self.q, 1e-12)

    def correction(self, noise, reuse, k=2., confidence="hard", minimum_count=8.):
        eligible = ((self.age >= 8) & (self.effective_count >= minimum_count)
                    & reuse & np.all(np.isfinite(self.mean), axis=(0, 3)))
        threshold2 = (float(k)*noise)**2
        if confidence == "hard":
            weight = (self.mean**2 > threshold2).astype(np.float32)
        elif confidence == "soft":
            weight = np.maximum(0, 1-threshold2/np.maximum(self.mean**2, 1e-20))
        elif confidence == "rgb_soft":
            signal2 = np.sum(self.mean**2, axis=-1, keepdims=True)
            noise2 = np.sum(threshold2, axis=-1, keepdims=True)
            weight = np.maximum(0, 1-noise2/np.maximum(signal2, 1e-20))
        else:
            raise ValueError("Unknown confidence rule: "+confidence)
        return np.where(eligible[None, ..., None], self.mean*weight, 0)


def identity_taps(h, w):
    y, x = np.indices((h, w))
    return [(y, x, np.ones((h, w), np.float32))]
