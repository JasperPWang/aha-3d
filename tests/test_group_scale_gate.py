import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("group_scale_gate",Path(__file__).resolve().parents[1]/"tools/gvhmr/group_scale_gate.py")
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)


class GroupScaleGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.manifest={"actors":[],"group_alignment":{"report":"group.json"},"render":{"camera_cache":"camera"}}
        (self.base/"camera").write_bytes(b"camera")
        rows=[]
        for i in range(2):
            (self.base/f"{i}.json").write_text(json.dumps({"body_scale":1.0}))
            (self.base/f"{i}.npz").write_bytes(b"fixture")
            self.manifest["actors"].append({"id":str(i),"alignment":f"{i}.json","cache":f"{i}.npz"})
            rows.append({"id":str(i),"alignment_sha256":gate.digest(self.base/f"{i}.json"),
                         "cache_sha256":gate.digest(self.base/f"{i}.npz")})
        self.report={"schema_version":1,"accepted":True,"shared_scale":1.0,"scale_policy":"native_units_locked","scale_optimized":False,"actors":rows,
                     "camera_sha256":gate.digest(self.base/"camera")}
        self.save()
    def save(self):
        (self.base/"group.json").write_text(json.dumps(self.report))
    def test_shared_bound_inputs_pass(self):
        self.assertEqual(gate.validate_group(self.manifest,self.base)["shared_scale"],1.0)
    def test_old_individual_scale_rejected(self):
        (self.base/"1.json").write_text('{"body_scale":0.7}')
        with self.assertRaisesRegex(ValueError,"Independent actor scales"):
            gate.validate_group(self.manifest,self.base)
    def test_equal_scale_without_evidence_rejected(self):
        del self.manifest["group_alignment"]
        with self.assertRaisesRegex(ValueError,"requires an accepted"):
            gate.validate_group(self.manifest,self.base)
    def test_unaccepted_projection_rejected(self):
        self.report["accepted"]=False;self.save()
        with self.assertRaisesRegex(ValueError,"not passed"):
            gate.validate_group(self.manifest,self.base)
    def test_changed_cache_rejected(self):
        (self.base/"0.npz").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError,"input changed"):
            gate.validate_group(self.manifest,self.base)
    def test_changed_camera_rejected(self):
        (self.base/"camera").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError,"camera differs"):
            gate.validate_group(self.manifest,self.base)
    def test_equal_but_fitted_scale_rejected(self):
        for i in range(2):
            (self.base/f"{i}.json").write_text('{"body_scale":0.95}')
        with self.assertRaisesRegex(ValueError,"Native human units are locked"):
            gate.validate_group(self.manifest,self.base)
    def test_old_scale_fit_report_rejected(self):
        self.report["scale_optimized"]=True;self.save()
        with self.assertRaisesRegex(ValueError,"without scale optimization"):
            gate.validate_group(self.manifest,self.base)
    def test_changed_pose_evidence_rejected(self):
        (self.base/"confidence.pt").write_bytes(b"old")
        self.manifest["actors"][0]["pose_confidence"]="confidence.pt"
        self.report["actors"][0]["pose_evidence"]={"sha256":gate.digest(self.base/"confidence.pt")}
        self.save()
        (self.base/"confidence.pt").write_bytes(b"new")
        with self.assertRaisesRegex(ValueError,"Pose confidence evidence changed"):
            gate.validate_group(self.manifest,self.base)
    def test_wrong_report_scale_rejected(self):
        self.report["shared_scale"]=1.1;self.save()
        with self.assertRaisesRegex(ValueError,"scale differs"):
            gate.validate_group(self.manifest,self.base)
if __name__=="__main__":
    unittest.main()
