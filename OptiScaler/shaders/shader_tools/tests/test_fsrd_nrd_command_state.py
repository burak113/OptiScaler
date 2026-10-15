"""Exact production state/predication and dual-root restoration regressions.

Default source checks are CPU-only. --run compiles one native CPU helper after
the lead's grant. The helper preserves the existing root/Birth assertion suite
and adds explicit COM-ABI recording adapters; no D3D runtime/GPU is claimed.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import unittest

import test_fsrd_nrd_root_birth as born
from test_fsrd_nrd_root_restore import function

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
SOURCE = ROOT/'OptiScaler/hooks/D3D12_Hooks.cpp'


class SourceProof(unittest.TestCase):
    def test_missing_predicate_is_unknown(self):
        proof = function(SOURCE.read_text(), 'static bool BridgePredicateDisabledLocked(')
        self.assertIn('found != bridgePredicates.end()', proof)
        self.assertIn('BridgePredication::Disabled', proof)
        self.assertIn('found->second.receiverBirth == receiver', proof)

    def test_clear_is_not_a_recording_reset(self):
        body = function(SOURCE.read_text(), 'void D3D12Hooks::OnBridgeCommandListClearState(')
        self.assertNotIn('RecordedComputeLease', body)
        self.assertNotIn('NrdBridge::OnReset', body)
        self.assertIn('OnBridgeCommandListReset(list,initial)', body)

    def test_graphics_guards_keep_bridge_and_nested_proof(self):
        text = SOURCE.read_text()
        for name in ('hkSetGraphicsRootSignature', 'hkSetGraphicsRootSignatureLate'):
            body = function(text, 'static void '+name+'(')
            self.assertIn('(gNrdBridgeDeviceWrappers || Config::Instance()->RestoreGraphicSignature.value_or_default())', body)
        early = function(text, 'static void hkSetGraphicsRootUnorderedAccessView(')
        self.assertIn('if (!lateInProgressSetGraphicsRootUnorderedAccessView', early)

    def test_graphics_replay_is_both_families_and_pso_last(self):
        body = function(SOURCE.read_text(), 'bool D3D12Hooks::RestoreGraphicsRootForBridge(')
        order = [body.index(value) for value in ('RestoreDescriptorHeaps',
                 's_SetComputeRootSignature', 'RestoreComputeRootState',
                 's_SetGraphicsRootSignature', 'RestoreGraphicsRootState', 'RestorePipelineState')]
        self.assertEqual(order, sorted(order))
        self.assertNotIn('Config::Instance()', body)

    def test_actual_sdk_vtable_slots_and_both_assignments(self):
        sdk = Path(os.environ.get('FSRD_D3D12_HEADER', 'C:/Program Files (x86)/Windows Kits/10/Include/10.0.26100.0/um/d3d12.h'))
        block = sdk.read_text().split('typedef struct ID3D12GraphicsCommandListVtbl', 1)[1].split('} ID3D12GraphicsCommandListVtbl;', 1)[0]
        names = re.findall(r'\(\s*STDMETHODCALLTYPE\s*\*(\w+)\s*\)', block)
        text = SOURCE.read_text(); reader = function(text, 'static void ReadBridgeGraphicsArgumentHooks(')
        for name, index in [('SetGraphicsRootDescriptorTable', 32), ('SetGraphicsRoot32BitConstant', 34),
                            ('SetGraphicsRoot32BitConstants', 36), ('SetGraphicsRootConstantBufferView', 38),
                            ('SetGraphicsRootShaderResourceView', 40), ('SetGraphicsRootUnorderedAccessView', 42)]:
            self.assertEqual(names[index], name)
            for mode in ('early', 'late'):
                self.assertIn(f's_{name}.o_{mode}Hook = (PFN_{name}) table[{index}]', reader)
        self.assertEqual(names[11], 'ClearState'); self.assertEqual(names[55], 'SetPredication')

    def test_actual_installers_use_shared_extension_and_actual_unhook(self):
        text = SOURCE.read_text()
        early = function(text, 'static void HookToCommandList(')
        late = function(text, 'void D3D12Hooks::HookToCommandListLate(')
        for body, mode in ((early, 'false'), (late, 'true')):
            self.assertIn(f'ReadBridgeGraphicsArgumentHooks(pVTable,{mode})', body)
            self.assertIn(f'AttachBridgeGraphicsArgumentHooks({mode})', body)
            self.assertIn('DetourTransactionAbort()', body)
            self.assertIn(f'ClearBridgeGraphicsArgumentHooks({mode})', body)
        unhook = function(text, 'void D3D12Hooks::Unhook(')
        self.assertLess(unhook.index('UnhookBridgeGraphicsArguments()'), unhook.index('if (o_D3D12CreateDevice == nullptr)'))


def run():
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    if out.exists():
        raise AssertionError('fresh output required; preserve every negative')
    os.environ['FSRD_ROOT_BIRTH_GENERATE_ONLY'] = '1'
    try:
        original = born.run()
    finally:
        del os.environ['FSRD_ROOT_BIRTH_GENERATE_ONLY']
    cpp = original.read_text()
    marker = 'int main(int argc,char**argv)try{'
    assert cpp.count(marker) == 1 and cpp.count(' rootBirthCases();') == 1
    production = SOURCE.read_text()
    installers = production[production.index('// These six argument hooks'):production.index('void D3D12Hooks::HookToCommandListLate(')]
    for name in ('hkSetPipelineStateLate', 'hkSetDescriptorHeapsLate'):
        installers += '\n'+function(production, 'static void '+name+'(')
    installers += '\n'+function(production, 'void D3D12Hooks::HookToCommandListLate(')
    install_fixture = (HERE/'fsrd_nrd_graphics_installer_fixture.cpp').read_text().replace('__INSTALLER_BODIES__', installers)
    cpp = cpp.replace('struct D3D12Hooks{', 'struct D3D12Hooks{\n static void HookToCommandListLate(ID3D12GraphicsCommandList*);')
    cpp = cpp.replace(marker, install_fixture+'\n'+(HERE/'fsrd_nrd_command_state_fixture.cpp').read_text()+'\n'+marker)
    cpp = cpp.replace(' rootBirthCases();', ' rootBirthCases();\n commandStateCases();')
    cpp = cpp.replace(' commandStateCases();', ' graphicsInstallerCases();\n commandStateCases();')
    source, exe = out/'command_state.cpp', out/'command_state.exe'
    source.write_text(cpp)
    born.base.compile_cpp(source, exe, libraries=['bcrypt.lib'])
    completed = subprocess.run([str(exe)], capture_output=True, text=True, timeout=45)
    (out/'native.stdout.txt').write_text(completed.stdout)
    (out/'native.stderr.txt').write_text(completed.stderr)
    print(completed.stdout, end=''); print(completed.stderr, end='')
    result = dict(exit_code=completed.returncode, source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                  generated_cpp_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  executable_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(), stdout=completed.stdout,
                  stderr=completed.stderr, assertions_preserved='complete root restore and positive activated Birth suite',
                  actual_production_trackers=True, actual_birth_protocol=True,
                  scope='native CPU explicit COM ABI/recording adapters; no D3D runtime, physical detours or GPU')
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    completed.check_returncode()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    tests = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SourceProof))
    if not tests.wasSuccessful(): raise SystemExit(1)
    if args.run: run()
