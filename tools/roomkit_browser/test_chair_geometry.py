import math
import unittest
from chair_geometry import forward_table_distance


class FacingAssociations(unittest.TestCase):
    def test_long_table_end_chair_faces_the_edge(self):
        table = [(-.5,-2), (.5,-2), (.5,2), (-.5,2)]
        self.assertAlmostEqual(forward_table_distance(table, (-.65,-1.8), math.pi/2), .15)
        self.assertIsNone(forward_table_distance(table, (-.65,-1.8), -math.pi/2))
        self.assertEqual(forward_table_distance(table, (-.4,-1.8), math.pi/2), 0)

    def test_association_is_invariant_to_room_rotation(self):
        angle = math.radians(-18)
        def rotate(p):
            return math.cos(angle)*p[0]-math.sin(angle)*p[1], math.sin(angle)*p[0]+math.cos(angle)*p[1]
        table = list(map(rotate, [(-.5,-2), (.5,-2), (.5,2), (-.5,2)]))
        self.assertAlmostEqual(forward_table_distance(table, rotate((-.65,-1.8)), math.pi/2+angle), .15)


if __name__ == '__main__':
    unittest.main()
