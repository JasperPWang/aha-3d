"""Pure recipe contract checks; run with PYTHONPATH=src."""
import copy
import unittest

from aha3d.blender.variants import class_matches, validate_recipe


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.recipe = {'schema_version': 1, 'seed': 42, 'models': [
            {'selector': {'semantic_class': 'furniture/seating/chairs'},
             'asset_id': 'roomkit-v1/chair-walnut-lounge', 'fit': 'native'}]}

    def test_hierarchical_selection_respects_boundaries(self):
        self.assertTrue(class_matches('furniture/seating/chairs/lounge', 'furniture/seating/chairs'))
        self.assertFalse(class_matches('furniture/seating/chairs_extra', 'furniture/seating/chairs'))
        self.assertFalse(class_matches('furniture/seating/stools', 'furniture/seating/chairs'))

    def test_requires_explicit_fit_and_selector(self):
        for key in ('fit', 'selector'):
            recipe = copy.deepcopy(self.recipe)
            del recipe['models'][0][key]
            with self.assertRaises(ValueError):
                validate_recipe(recipe)

    def test_rejects_typos_and_empty_selectors(self):
        for selector in ({'instance_ids': []}, {'semantic_class': ''}, {'semantic_class': 'a', 'instance_ids': ['b']}, {'class': 'a'}):
            recipe = copy.deepcopy(self.recipe)
            recipe['models'][0]['selector'] = selector
            with self.assertRaises(ValueError):
                validate_recipe(recipe)

    def test_seed_and_parameters_are_finite(self):
        for seed in (True, 1.5, '42'):
            recipe = copy.deepcopy(self.recipe)
            recipe['seed'] = seed
            with self.assertRaises(ValueError):
                validate_recipe(recipe)
        for params in ({'roughness': float('nan')}, {'color': [1, 1, 2]}, {'texture_scale': 4}):
            with self.assertRaises(ValueError):
                validate_recipe({'schema_version': 1, 'materials': [
                    {'surface_role': 'wall_finish', 'asset_id': 'material', 'parameters': params}]})

    def test_validated_recipe_is_independent(self):
        result = validate_recipe(self.recipe)
        result['models'][0]['fit'] = 'uniform_footprint'
        self.assertEqual(self.recipe['models'][0]['fit'], 'native')


if __name__ == '__main__':
    unittest.main()
