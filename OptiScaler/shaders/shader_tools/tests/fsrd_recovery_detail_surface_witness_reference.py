"""Ablation: original band mean certified by a same-surface temporal witness.

The local paired mean is a veto, never an alternative color source. Constant
paired differences within disconnected surfaces cannot certify their global
box boundary response. Surface-local DC and current availability stay required.
Two RGB moment populations are deliberately retained in this CPU prototype;
their cost is not claimed as a production solution.
"""
import numpy as np
from fsrd_recovery_detail_reference import PairedBandMoments
from fsrd_recovery_detail_geometry_reference import GeometryObservations, GeometryState


class SurfaceWitnessMoments(PairedBandMoments):
    def __post_init__(self):
        self.output_bands = self.bands
        self.bands *= 2
        super().__post_init__()

    def update(self, observations, taps, reuse):
        observations = np.asarray(observations, np.float32)
        expected = (self.output_bands, 2, *self.shape, 3)
        if observations.shape != expected:
            raise ValueError((observations.shape, expected))
        return super().update(observations.reshape(self.mean.shape), taps, reuse)

    def correction(self, noise, reuse, k=2., confidence="soft", minimum_count=8.):
        certified = super().correction(noise, reuse, k, confidence, minimum_count)
        global_correction = certified[0::2]
        local_correction = certified[1::2]
        local_mean = self.mean[1::2]
        weight = np.divide(local_correction, local_mean,
            out=np.zeros_like(local_mean), where=local_mean != 0)
        return global_correction*np.clip(weight, 0, 1)


class WitnessObservations(GeometryObservations):
    global_band = None

    def band(self, values, small, large):
        if self.global_band is None:
            raise RuntimeError("Exact original band operator has not been supplied")
        return np.stack((self.global_band(values, small, large),
                         super().band(values, small, large)))


class WitnessState(GeometryState):
    def __init__(self, gate, width, height):
        # Test-process implementation substitution only. The frozen geometry
        # reference bytes and original failed reports remain untouched.
        import fsrd_recovery_detail_geometry_reference as geometry
        WitnessObservations.global_band = staticmethod(gate.band)
        geometry.GeometryObservations = WitnessObservations
        geometry.PairedBandMoments = SurfaceWitnessMoments
        super().__init__(gate, width, height)
