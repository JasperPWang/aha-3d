"""Pure semantic orientation contract tests."""
import copy
import math
import unittest

from aha3d.orientation import canonical_orientation, canonical_rotation, normalize_orientation


AXES = {'X': (1, 0, 0), '-X': (-1, 0, 0), 'Y': (0, 1, 0), '-Y': (0, -1, 0),
        'Z': (0, 0, 1), '-Z': (0, 0, -1)}


def orientation(front='-Y', up='Z', **updates):
    result = {'schema_version': 1, 'front_axis': front, 'up_axis': up,
              'symmetry': 'none', 'origin': 'floor_center', 'semantic_front': 'seating',
              'status': 'authored', 'evidence': 'Synthetic asymmetric fixture with marked front and top.'}
    result.update(updates)
    return result


def apply(matrix, vector):
    return tuple(sum(float(matrix[row][column]) * vector[column] for column in range(3)) for row in range(3))


def determinant(matrix):
    a, b, c = matrix
    return (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0]))


class OrientationTests(unittest.TestCase):
    def assertVectorClose(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for observed, wanted in zip(actual, expected):
            self.assertAlmostEqual(observed, wanted, places=7)

    def test_all_24_orthogonal_source_frames_become_canonical_without_reflection(self):
        count = 0
        for front, front_vector in AXES.items():
            for up, up_vector in AXES.items():
                if sum(a * b for a, b in zip(front_vector, up_vector)):
                    continue
                with self.subTest(front=front, up=up):
                    matrix = canonical_rotation(orientation(front, up))
                    self.assertVectorClose(apply(matrix, front_vector), (0, -1, 0))
                    self.assertVectorClose(apply(matrix, up_vector), (0, 0, 1))
                    self.assertAlmostEqual(determinant(matrix), 1., places=7)
                    count += 1
        self.assertEqual(count, 24)

    def test_source_x_and_y_correction_has_the_correct_clockwise_sign(self):
        plus_x = canonical_rotation(orientation('X'))
        self.assertVectorClose(apply(plus_x, (1, 0, 0)), (0, -1, 0))
        self.assertVectorClose(apply(plus_x, (0, 1, 0)), (1, 0, 0))
        plus_y = canonical_rotation(orientation('Y'))
        self.assertVectorClose(apply(plus_y, (0, 1, 0)), (0, -1, 0))
        self.assertVectorClose(apply(plus_y, (1, 0, 0)), (-1, 0, 0))

    def test_canonical_metadata_preserves_semantic_origin_and_provenance(self):
        source = orientation('X', semantic_front='spout', origin='mount_center')
        original = copy.deepcopy(source)
        result = canonical_orientation(source)
        self.assertEqual(result['front_axis'], '-Y')
        self.assertEqual(result['up_axis'], 'Z')
        self.assertEqual(result['origin'], 'mount_center')
        self.assertEqual(result['semantic_front'], 'spout')
        self.assertEqual(result['status'], 'authored')
        self.assertEqual(result['evidence'], source['evidence'])
        self.assertEqual(source, original)

    def test_declared_or_unknown_metadata_does_not_become_trusted(self):
        for status in ('unknown', 'declared'):
            source = orientation(status=status)
            self.assertEqual(normalize_orientation(source)['status'], status)
            with self.assertRaises(ValueError):
                normalize_orientation(source, require_trusted=True)
        for status in ('authored', 'reviewed'):
            self.assertEqual(normalize_orientation(orientation(status=status), require_trusted=True)['status'], status)
            with self.assertRaises(ValueError):
                normalize_orientation(orientation(status=status, evidence=''), require_trusted=True)

    def test_symmetric_objects_have_no_invented_front(self):
        source = orientation(None, symmetry='continuous_z', semantic_front='none')
        normalized = normalize_orientation(source, require_trusted=True)
        canonical = canonical_orientation(source)
        self.assertIsNone(normalized['front_axis'])
        self.assertIsNone(canonical['front_axis'])
        self.assertEqual(canonical['semantic_front'], 'none')
        self.assertVectorClose(apply(canonical_rotation(source), (0, 0, 1)), (0, 0, 1))

    def test_parallel_axes_and_invalid_enums_are_rejected(self):
        malformed = [orientation('Z', 'Z'), orientation('-Z', 'Z'), orientation('banana'),
                     orientation(up='Q'), orientation(origin='bounds_min'), orientation(status='probably'),
                     orientation(symmetry='almost_round'), orientation(semantic_front='looks_frontish'),
                     orientation(schema_version=True), orientation(schema_version=2)]
        for source in malformed:
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    normalize_orientation(source)

    def test_symmetric_and_directional_declarations_must_be_consistent(self):
        for source in (orientation('Y', symmetry='continuous_z', semantic_front='none'),
                       orientation(None, symmetry='continuous_z', semantic_front='spout')):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    normalize_orientation(source)


if __name__ == '__main__':
    unittest.main()
