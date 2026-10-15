"""CPU structure/constants proof; never compiles or executes a shader."""
import struct
import tempfile
from pathlib import Path
import unittest
from fsrd_gpu_chain import ChainJob
from fsrd_nrd_lobe_recovery_graph import LobeGraph,constants,HISTORY,COARSEST,FINAL


class LobeGraphContracts(unittest.TestCase):
    def test_exact_cb128_and_provided_jitter_delta(self):
        words = struct.unpack('<28f4I',constants(1505,847,(1505,847,753,424),0,HISTORY,27,
            jitter=(.25,-.125),jitter_delta_uv=(.5/1505,-.25/847)))
        self.assertEqual(words[12:14],(.25,-.125))
        self.assertAlmostEqual(words[14],.5/1505,places=10)
        self.assertEqual(words[28:],(HISTORY,0,27,0))

    def graph(self,directory,storage='fp32'):
        job = ChainJob(directory,None)
        shaders = {name:dict(output=str(Path(directory)/(name+'.cso'))) for name in ('Reference','Down','Band')}
        graph = LobeGraph(job,shaders,33,29,storage=storage)
        # Only descriptor identities are needed for this CPU source test.
        from fsrd_nrd_lobe_recovery_graph import zero_texture
        inputs = {name:zero_texture(job,name,(33,29),format=24 if name=='normals' else 41 if name=='depth' else 10)
                  for name in ('spec','diff','rr_spec','rr_diff','depth','normals','motion')}
        return job,graph,inputs

    def test_complete13_passes_and_typed_history(self):
        with tempfile.TemporaryDirectory(prefix='nrd_recovery_graph_',dir='F:/FSRD/tmp') as directory:
            job,graph,inputs = self.graph(directory)
            graph.record(0,inputs)
            self.assertEqual(len(job.passes),13)
            self.assertEqual(graph.sizes,[(33,29),(17,15),(9,8),(5,4),(3,2),(2,1),(1,1)])
            self.assertEqual([len(p['srvs']) for p in job.passes],[11]+[3]*6+[18]*6)
            self.assertEqual([len(p['uavs']) for p in job.passes],[7]+[3]*6+[5]*6)
            geom = job.resources[job.names[graph.history[0]['geometry']]]
            self.assertEqual(geom['format'],3)
            self.assertEqual(geom['input'],Path('-'))
            self.assertTrue(all(not p['mode'] for p in job.passes))

    def test_first_reset_and_later_history_flags(self):
        with tempfile.TemporaryDirectory(prefix='nrd_recovery_graph_',dir='F:/FSRD/tmp') as directory:
            job,graph,inputs = self.graph(directory)
            graph.record(0,inputs)
            graph.record(1,inputs)
            flags = [struct.unpack('<28f4I',Path(p['constants']).read_bytes())[28] for p in job.passes]
            self.assertEqual(flags[:13],[0]*7+[COARSEST]+[0]*4+[FINAL])
            self.assertEqual(flags[13:],[HISTORY]*7+[HISTORY|COARSEST]+[HISTORY]*4+[HISTORY|FINAL])

    def test_current_rr_and_final_outputs_never_alias(self):
        with tempfile.TemporaryDirectory(prefix='nrd_recovery_graph_',dir='F:/FSRD/tmp') as directory:
            job,graph,inputs = self.graph(directory)
            output = graph.record(0,inputs)
            self.assertNotEqual(output['spec'],inputs['rr_spec'])
            self.assertNotEqual(output['diff'],inputs['rr_diff'])
            for p in job.passes:
                self.assertFalse(set(p['srvs']).intersection(p['uavs']).difference({-1,-2,-3}))

    def test_mixed_storage_keeps_noise_fp32_and_geometry_uint(self):
        with tempfile.TemporaryDirectory(prefix='nrd_recovery_graph_',dir='F:/FSRD/tmp') as directory:
            job,graph,inputs = self.graph(directory,'mixed')
            output=graph.record(0,inputs)
            fmt=lambda name:job.resources[job.names[name]]['format']
            for history in graph.history:
                self.assertEqual(fmt(history['geometry']),3)
                self.assertTrue(all(fmt(history[name])==10 for name in ('spec','diff','gradient')))
                self.assertTrue(all(fmt(name)==2 for name in history['noise']))
            for level in graph.levels:
                self.assertTrue(all(fmt(name)==10 for name in level.values()))
            for correction in graph.corrections:
                self.assertTrue(all(fmt(name)==10 for name in correction.values()))
            self.assertTrue(all(fmt(name)==10 for name in output.values()))

    def test_storage_changes_only_formats_not_graph_math_or_inputs(self):
        with tempfile.TemporaryDirectory(prefix='nrd_recovery_graph_',dir='F:/FSRD/tmp') as parent:
            jobs=[]
            for mode in ('fp32','mixed'):
                job,graph,inputs=self.graph(Path(parent)/mode,mode)
                graph.record(0,inputs,jitter=(.25,-.125),jitter_delta_uv=(1/33,-1/29))
                jobs.append((job,graph,inputs))
            a,b=jobs
            for pa,pb in zip(a[0].passes,b[0].passes):
                self.assertEqual(Path(pa['constants']).read_bytes(),Path(pb['constants']).read_bytes())
                for key in ('name','srvs','uavs','groups','mode'):
                    self.assertEqual(pa[key],pb[key])
            for name in a[2]:
                self.assertEqual(a[0].resources[a[0].names[a[2][name]]]['format'],b[0].resources[b[0].names[b[2][name]]]['format'])
            self.assertLess(b[1].allocated_native_bytes(),a[1].allocated_native_bytes())

    def test_unknown_storage_rejected_before_graph_allocation(self):
        with tempfile.TemporaryDirectory(prefix='nrd_recovery_graph_',dir='F:/FSRD/tmp') as directory:
            with self.assertRaises(ValueError):self.graph(directory,'half_noise')


if __name__ == '__main__':
    unittest.main()
