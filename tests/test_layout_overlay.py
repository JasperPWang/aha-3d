import unittest
import numpy as np
from tools.layout_inspection.overlay import alpha_over


class OverlayTests(unittest.TestCase):
    def test_hidden_edge_replaces_opaque_reference(self):
        reference = np.array([[[.2, .4, .6, 1.], [.2, .4, .6, 1.]]])
        edges = np.array([[[1., .2, 0., 1.], [1., .2, 0., 0.]]])
        result = alpha_over(reference, edges)
        np.testing.assert_array_equal(result[0, 0], edges[0, 0])
        np.testing.assert_array_equal(result[0, 1], reference[0, 1])

    def test_antialiased_edge_and_empty_pass(self):
        reference = np.array([[[.2, .4, .6, 1.]]])
        edges = np.array([[[1., .2, 0., .5]]])
        np.testing.assert_allclose(alpha_over(reference, edges), [[[.6, .3, .3, 1.]]])
        np.testing.assert_array_equal(alpha_over(reference, np.zeros_like(reference)), reference)

    def test_mismatched_projections_rejected(self):
        with self.assertRaises(ValueError):
            alpha_over(np.zeros((2, 2, 4)), np.zeros((3, 2, 4)))


if __name__ == '__main__':
    unittest.main()
