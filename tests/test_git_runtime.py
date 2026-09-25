"""The deployed checkout keeps runtime overrides private and records source identity."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from aha3d.config import load_runtime
from aha3d.provenance import git_identity
from aha3d.paths import migrated_path
from tools.verify_package import source_files
from tools.build_catalog import Catalog

ROOT = Path(__file__).resolve().parents[1]


class GitRuntime(unittest.TestCase):
    def test_local_path_aliases_preserve_legacy_data_locations(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'configs').mkdir()
            (root/'configs/path_migrations.json').write_text(json.dumps(dict(schema_version=1,paths={})))
            self.assertEqual(migrated_path(root,'old/frame.png'),root/'old/frame.png')
            (root/'configs/path_migrations.local.json').write_text(json.dumps(dict(schema_version=1,paths={'old':'scenes/kept'})))
            self.assertEqual(migrated_path(root,'old/frame.png'),root/'scenes/kept/frame.png')

    def test_runtime_local_override_and_portable_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); folder=root/'configs/runtimes';folder.mkdir(parents=True)
            for name in ('python','blender','skin','env','upstream','checkpoint','local_python'):
                (root/name).touch()
            cfg=dict(schema_version=2, python='python', blender='blender',skin_blender='skin',
                env_script='env',upstream='upstream',checkpoint='checkpoint',threads=4,gpu=0)
            (folder/'example.json').write_text(json.dumps(cfg))
            self.assertEqual(load_runtime(root,'example')['python'],str(root/'python'))
            cfg['python']='local_python';(folder/'example.local.json').write_text(json.dumps(cfg))
            self.assertEqual(load_runtime(root,'example')['python'],str(root/'local_python'))
            (folder/'example.local.json').write_text('{')
            with self.assertRaises(json.JSONDecodeError):load_runtime(root,'example')

    def test_local_shell_defaults_respect_the_caller_and_checkout(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'kimodo_blender';folder.mkdir()
            shutil.copyfile(ROOT/'kimodo_blender/env.sh',folder/'env.sh')
            (folder/'env.local.sh').write_text('export KIMODO_ENV="${KIMODO_ENV:-/configured/core}"\nexport PI3X_MESH_PY="${PI3X_MESH_PY:-/configured/mesh}"\n')
            script='source "$1"; printf "%s\\n" "$KIMODO_ENV" "$PI3X_MESH_PY" "$INDOOR_PROJECT_ROOT"'
            env={k:v for k,v in os.environ.items() if k not in ('KIMODO_ENV','PI3X_MESH_PY')}
            def run():return subprocess.check_output(['bash','-c',script,'test',str(folder/'env.sh')],env=env,text=True).splitlines()
            self.assertEqual(run(),['/configured/core','/configured/mesh',str(root)])
            env['KIMODO_ENV']='/caller/core';self.assertEqual(run()[0],'/caller/core')

    def test_git_identity_clean_dirty_and_unversioned(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            self.assertEqual(git_identity(root),{'kind':'unversioned'})
            def git(*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.DEVNULL,text=True).strip()
            git('init');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
            (root/'code.py').write_text('pass\n');git('add','code.py');git('commit','-m','Fixture')
            clean=git_identity(root);self.assertEqual(clean['commit'],git('rev-parse','HEAD'));self.assertFalse(clean['dirty'])
            (root/'code.py').write_text('value=1\n');self.assertTrue(git_identity(root)['dirty'])
            sub=root/'child';sub.mkdir();self.assertEqual(git_identity(sub),{'kind':'unversioned'})
            git('checkout','--','code.py');git('checkout','--detach');self.assertIsNone(git_identity(root)['branch'])

    def test_package_inventory_excludes_installed_runtime_and_keeps_new_code(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            subprocess.run(['git','init',str(root)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            (root/'.gitignore').write_text('.runtime/\n*.local.json\n')
            (root/'new.py').write_text('pass\n');(root/'profile.local.json').write_text('{}')
            (root/'.runtime').mkdir();(root/'.runtime/model.py').write_text('private runtime')
            paths={p.relative_to(root).as_posix() for p in source_files(root)}
            self.assertEqual(paths,{'.gitignore','new.py'})
            catalog=Catalog(root)
            self.assertIsNone(catalog.url('.runtime/model.py'))
            self.assertIsNone(catalog.url('profile.local.json'))
            self.assertEqual(catalog.url('new.py'),'../../new.py')


if __name__=='__main__':unittest.main()
