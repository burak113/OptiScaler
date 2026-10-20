"""Integration check: missing donor provenance must fail closed at BOTH APIs."""
import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reconstruction import GeometryField,certify_cells,local_estimator_support,certify_estimator_support


class CertificateContract(unittest.TestCase):
    def test_numeric_or_nan_donor_validity_is_not_a_boolean_certificate(self):
        y,x=np.mgrid[:8,:8]
        positions=np.stack((x,y,np.full_like(x,5)),axis=-1).astype(float)
        normals=np.zeros_like(positions);normals[...,2]=1
        mask=np.ones((8,8),bool)
        cells=certify_cells(GeometryField(positions,normals,mask,mask))
        for value in (float('nan'),0.,1.):
            with self.subTest(value=value):
                bad=np.full((1,1),value)
                with self.assertRaises(ValueError):local_estimator_support(cells,bad)
                with self.assertRaises(ValueError):
                    certify_estimator_support(cells,np.ones((1,1)),bad,[(0,0)])


if __name__=='__main__':unittest.main()
