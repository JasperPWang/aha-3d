import unittest
import numpy as np
from tools.layout_inspection.prepare import require_full_coverage


class FrameCoverage(unittest.TestCase):
    def test_all_frames_in_each_tier(self):
        for count in (32, 64):
            ids = np.linspace(0, 251, count).round().astype(int)
            require_full_coverage(ids, None, np.ones(count, bool))
            require_full_coverage(ids, ids.tolist(), np.ones(count, bool))
            with self.assertRaisesRegex(ValueError, 'all cached frames'):
                require_full_coverage(ids, [int(ids[0]), int(ids[count//2]), int(ids[-1])])

    def test_partial_semantics_cannot_hide_other_frames(self):
        ids = np.arange(32)
        known = np.zeros(32, bool)
        known[[0, 16, 31]] = True
        with self.assertRaisesRegex(ValueError, 'Semantic cache must cover all'):
            require_full_coverage(ids, None, known)


if __name__ == '__main__':
    unittest.main()
