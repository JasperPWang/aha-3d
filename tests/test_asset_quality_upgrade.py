"""Current-payload publication must reject incomplete or stale staged inputs."""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('quality_integrate',ROOT/'tools/asset_quality_upgrade/integrate.py')
module=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(module)


class QualityPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'assets').mkdir();(self.root/'stage').mkdir()
        self.source=self.root/'assets/library.blend';self.source.write_bytes(b'original')
        self.candidate=self.root/'stage/library.blend';self.candidate.write_bytes(b'improved')
        self.metadata=self.root/'assets/manifest.json';module.write(self.metadata,{'furniture':[{'name':'Cup'}]})
        self.new_metadata=self.root/'stage/manifest.json';module.write(self.new_metadata,{'furniture':[{'name':'Cup','quality':'reviewed'}]})
        registry={'assets':{'cups':{'path':'assets/library.blend','sha256':module.digest(self.source),'metadata':'assets/manifest.json'}}}
        module.write(self.root/'assets/registry.json',registry)
        module.write(self.root/'assets/orientation_reviews.json',{'schema_version':1,'reviews':{}})
        self.report=self.root/'stage/report.json'
        self.data={'status':'staged','registry_sha256':module.digest(self.root/'assets/registry.json'),
            'entries':[{'library_id':'cups','datablock':'Cup'}],
            'libraries':[{'id':'cups','original':'assets/library.blend','original_sha256':module.digest(self.source),
              'original_manifest_sha256':module.digest(self.metadata),'candidate':str(self.candidate),
              'candidate_sha256':module.digest(self.candidate),'manifest':str(self.new_metadata),
              'manifest_sha256':module.digest(self.new_metadata),'collections':{'Cup':{}}}]}

    def publish(self):
        module.write(self.report,self.data)
        with patch.object(module,'ROOT',self.root):module.publish(argparse.Namespace(report=self.report))

    def test_partial_staging_cannot_publish(self):
        self.data['status']='staging'
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual(self.source.read_bytes(),b'original')

    def test_missing_library_cannot_publish(self):
        self.data['libraries']=[]
        with self.assertRaisesRegex(ValueError,'coverage'):self.publish()
        self.assertEqual(self.source.read_bytes(),b'original')

    def test_changed_candidate_cannot_publish(self):
        self.candidate.write_bytes(b'unreviewed change')
        with self.assertRaisesRegex(ValueError,'bytes changed'):self.publish()
        self.assertEqual(self.source.read_bytes(),b'original')

    def test_missing_collection_cannot_publish(self):
        self.data['libraries'][0]['collections']={}
        with self.assertRaisesRegex(ValueError,'coverage'):self.publish()
        self.assertEqual(self.source.read_bytes(),b'original')

    def test_reviewed_current_payload_replaces_stable_path(self):
        self.publish()
        self.assertEqual(self.source.read_bytes(),b'improved')
        registry=json.loads((self.root/'assets/registry.json').read_text())
        self.assertEqual(set(registry['assets']),{'cups'})
        self.assertEqual(registry['assets']['cups']['path'],'assets/library.blend')
        self.assertEqual(registry['assets']['cups']['sha256'],module.digest(self.source))


if __name__=='__main__':unittest.main()
