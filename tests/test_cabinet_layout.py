"""Recipe constraints reject physically unusable cabinetry before Blender edits."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aha3d.cabinet_layout import cabinet_preset, normalize_layout


class CabinetLayoutTests(unittest.TestCase):
    def test_default_keeps_two_doors_and_top_drawer(self):
        plan = normalize_layout()
        sections = plan['columns'][0]['sections']
        self.assertEqual([s['front'] for s in sections], ['double_door', 'drawers'])
        self.assertEqual(len(sections[1]['drawer_heights']), 1)
        self.assertEqual(sections[0]['shelves'], [.5])
        self.assertLess(sections[0]['bottom'], sections[1]['bottom'])

    def test_proportions_account_for_physical_separators(self):
        recipe = {'columns': [
            {'width': 2, 'sections': [{'front': 'door_right', 'shelves': [.2, .6]}]},
            {'width': 1, 'sections': [{'height': 1, 'front': 'open'},
                                     {'height': 2, 'front': 'drawers', 'drawer_heights': [1, 2]}]},
        ]}
        original = copy.deepcopy(recipe)
        plan = normalize_layout(recipe, (1.8, .6, 1.2))
        left, right = plan['columns']
        self.assertAlmostEqual(left['width'] / right['width'], 2)
        self.assertAlmostEqual(sum(c['width'] for c in plan['columns']) + 3 * .024, 1.8)
        self.assertAlmostEqual(sum(s['height'] for s in right['sections']) + 3 * .024, 1.2)
        first, second = right['sections'][1]['drawer_heights']
        self.assertAlmostEqual(second / first, 2)
        self.assertEqual(recipe, original)

    def test_presets_are_independent_and_support_grid_interiors(self):
        preset = cabinet_preset('open_shelving')
        preset['columns'][0]['sections'][0]['shelves'] = 0
        plan = normalize_layout('open_shelving')
        self.assertEqual(len(plan['columns'][0]['sections'][0]['shelves']), 2)
        self.assertEqual(plan['columns'][0]['sections'][0]['dividers'], [.5])

    def test_drawer_count_is_not_hardcoded(self):
        for count in (1, 2, 3, 5, 8):
            plan = normalize_layout({'columns': [{'sections': [
                {'front': 'drawers', 'drawer_count': count}]}]}, (1.2, .55, 1.5))
            self.assertEqual(len(plan['columns'][0]['sections'][0]['drawer_heights']), count)

    def test_bad_layouts_are_rejected(self):
        bad = [
            {'columns': []}, {'column': []},
            {'columns': [{'sections': [{'front': 'magic'}]}]},
            {'columns': [{'sections': [{'front': 'drawers', 'drawer_count': 0}]}]},
            {'columns': [{'sections': [{'front': 'drawers', 'drawer_count': True}]}]},
            {'columns': [{'sections': [{'front': 'drawers', 'drawer_count': 40}]}]},
            {'columns': [{'sections': [{'front': 'drawers', 'drawer_heights': [1, -1]}]}]},
            {'columns': [{'sections': [{'front': 'drawers', 'drawer_count': 2, 'drawer_heights': [1, 1]}]}]},
            {'columns': [{'sections': [{'front': 'drawers', 'shelves': 1}]}]},
            {'columns': [{'sections': [{'front': 'open', 'drawer_count': 2}]}]},
            {'columns': [{'sections': [{'shelves': [.6, .3]}]}]},
            {'columns': [{'sections': [{'shelves': [.01, .5]}]}]},
            {'columns': [{'sections': [{'dividers': [0]}]}]},
            {'columns': [{'width': float('nan'), 'sections': [{}]}]},
            {'columns': [{'width': 100, 'sections': [{}]}, {'width': 1, 'sections': [{}]}]},
            {'columns': [{'sections': [{'height': 100}, {'height': 1}]}]},
        ]
        for recipe in bad:
            with self.subTest(recipe=recipe), self.assertRaises(ValueError):
                normalize_layout(recipe)

    def test_invalid_dimensions_and_limits(self):
        for size in ((0, 1, 1), (.1, .5, 1), (1, float('inf'), 1), (True, 1, 1), (1, 1)):
            with self.subTest(size=size), self.assertRaises(ValueError):
                normalize_layout(size=size)
        for key, value in [('panel_thickness', .3), ('gap', .2),
                           ('door_angle_degrees', 200), ('drawer_travel_fraction', 1.1)]:
            recipe = cabinet_preset('default')
            recipe[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                normalize_layout(recipe)


if __name__ == '__main__':
    unittest.main()
