"""Missing baselines are explicit skips; damaged or mismatched ones fail closed."""
from pathlib import Path
import hashlib
import json
import os
import tempfile
from unittest.mock import patch
import fsrd_references as refs


def run():
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        manifest=root/'hashes.json'
        manifest.write_text(json.dumps({'packages':{'fixture':{
            'shader.cso':hashlib.sha256(b'expected DXIL').hexdigest(),
            'shader.hlsl':hashlib.sha256(b'expected layout').hexdigest()}}}))
        with patch.object(refs,'MANIFEST',manifest), patch.dict(os.environ,{'FSRD_REFERENCE_ROOT':''}):
            assert refs.reference('fixture') is None
            os.environ['FSRD_REFERENCE_ROOT']=str(root)
            assert refs.reference('fixture') is None
            directory=root/'fixture/precompile';directory.mkdir(parents=True)
            for bad, layout in ((b'expected DXIL',None),(b'wrong DXIL',b'expected layout'),
                                (b'expected DXIL',b'wrong layout')):
                (directory/'shader.cso').write_bytes(bad)
                if layout is not None: (directory/'shader.hlsl').write_bytes(layout)
                try: refs.reference('fixture')
                except RuntimeError: pass
                else: raise AssertionError('Partial/tampered reference was accepted')
            (directory/'shader.cso').write_bytes(b'expected DXIL')
            (directory/'shader.hlsl').write_bytes(b'expected layout')
            assert refs.reference('fixture')==directory
    print('PASS: absent package skips; partial, DXIL and layout tampering fail; valid pair accepted')


if __name__=='__main__': run()
