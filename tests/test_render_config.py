import unittest
from aha3d.config import validate_recipe


class RenderConfig(unittest.TestCase):
    def recipe(self, render=None):
        value = dict(schema_version=1, scene='room', id='preview', source='room.blend',
                     timing=dict(fps=24, frames=24), body=dict(mode='keep'))
        if render is not None: value['render'] = render
        return validate_recipe(value)

    def test_defaults_and_explicit_quality(self):
        self.assertEqual(self.recipe()['render']['mode'], 'material')
        self.assertEqual(self.recipe()['render']['engine'], 'auto')
        for mode, engine in [('material','eevee'), ('material','cycles'), ('clay','workbench'),
                             ('clay','cycles'), ('preserve','auto')]:
            self.assertEqual(self.recipe(dict(mode=mode, engine=engine))['render']['engine'], engine)

    def test_reject_unsupported_engine_or_loss_of_material_shaders(self):
        for config in [dict(engine='opengl'), dict(mode='material',engine='workbench')]:
            with self.assertRaises(ValueError): self.recipe(config)
