"""Known-value checks for public PBR colour and ARM conversion."""
import unittest
import numpy as np
from prepare_rhino_assets import split_arm,tint_srgb


class AssetConversionTests(unittest.TestCase):
    def test_ao_strength_and_roughness_keep_scalar_metallic(self):
        # R=black is 30% AO after the viewer's 0.7 blend; G drives roughness.
        pixels=np.array([[[0,128,255],[255,255,0]]],dtype=np.uint8)
        ao,rough=split_arm(pixels,.5)
        np.testing.assert_allclose(ao,[[76.5,255]])
        np.testing.assert_allclose(rough,[[64,127.5]])

    def test_linear_tint_is_not_srgb_multiplication(self):
        pixels=np.array([[[255,128,0],[10,20,30]]],dtype=np.uint8)
        result=tint_srgb(pixels,[.5,1,0])
        self.assertAlmostEqual(result[0,0,0],187.516,places=2)
        self.assertAlmostEqual(result[0,0,1],128,places=8)
        self.assertTrue(np.all(result[...,2]==0))
        np.testing.assert_allclose(tint_srgb(pixels,[1,1,1]),pixels,atol=1e-10)


if __name__=='__main__': unittest.main()
