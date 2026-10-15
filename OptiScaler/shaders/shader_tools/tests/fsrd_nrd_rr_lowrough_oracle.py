"""NEW strictly positive r80 GGX physical reference; frozen V5 is unchanged.

This isolated process installs a named positive-domain sampler into the old
generator's reusable functions. No source, old data or zero-roughness shortcut
is changed. Later guide-only B46/B80 views test the explicit synthetic hypothesis
that native raw UNORM8 code20 represented perceptual roughness; it is not proved
by the captured title writer, whose upstream producer remains unavailable.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import fsrd_nrd_rr_ggx_oracle as frozen
import fsrd_nrd_rr_ggx_sampling as frozen_sampling
import fsrd_nrd_rr_lowrough_sampling as positive_sampling
import fsrd_nrd_rr_material_quality as sealed


CODE = 80
ORIGINAL_CONTRACT = frozen.source_contract


def source_contract(code, samples):
    if code != CODE:
        raise ValueError('this separate physical scenario has exactly positive packed roughness80/1023')
    result = ORIGINAL_CONTRACT(code, samples)
    result['source_files'].update({str(path): sealed.file_sha(path) for path in
        (Path(__file__), Path(frozen_sampling.__file__))})
    result.update(scenario='separate strictly positive r80 physical GGX hypothesis control',
        raw_native_unorm8_code=20, physical_perceptual_roughness=CODE / 1023.,
        native_mapping_hypothesis='raw20/255 interpreted as perceptual roughness, quantizedR10 raw80 versus nativeA*smoothstep(.04,.11,A) mapped46; upstream raw meaning is NOT proved',
        future_guide_axis='only packed guideB46 versus80; same physical RGB/A/references/primaryMV/chosenQs',
        sampler_extension='new separately hashed positive-domain fork, identical equations; frozenV5 guard/data unchanged; no zero or mirror shortcut',
        physical_signal_definition='F=1D*SmithVisibility*NoL/pdf physical outgoing radiance including hemisphericalQs; not already-demodulated native Recon',
        native_recon_unit_parity_claimed=False)
    return result


def install():
    frozen.sampling = positive_sampling
    frozen.ROUGHNESS_CODES = (CODE,)
    frozen.source_contract = source_contract


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first', type=int, default=0)
    parser.add_argument('--count', type=int, default=8)
    parser.add_argument('--samples', type=int, default=256)
    parser.add_argument('--output', type=Path, default=Path('F:/FSRD/sol_batch/15c-rr/ggx-lowrough-v6'))
    args = parser.parse_args()
    install()
    frozen.prepare_chunk(args.output, CODE, args.first, args.count, args.samples)
