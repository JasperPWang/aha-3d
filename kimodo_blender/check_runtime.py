"""Check actual CUDA execution, Kimodo imports and model access; never print tokens."""
import importlib
import json
import os
import platform
from pathlib import Path

import torch
from huggingface_hub import HfApi, hf_hub_download

root = Path(os.environ['KIMODO_ROOT'])
report = {'host': platform.node(), 'run_id': os.getenv('INDOOR_RUN_ID'),
          'cuda_visible_devices': os.getenv('CUDA_VISIBLE_DEVICES'),
          'python': platform.python_version(), 'torch': torch.__version__,
          'cuda': torch.version.cuda, 'cuda_available': torch.cuda.is_available()}
if not torch.cuda.is_available():
    raise RuntimeError('CUDA is unavailable; check the NVIDIA driver and CUDA_VISIBLE_DEVICES')
torch.cuda.set_device(0)
a = torch.randn((512, 512), device='cuda')
b = a @ a.T
torch.cuda.synchronize()
report['gpu'] = torch.cuda.get_device_name(0)
report['gpu_total_bytes'] = torch.cuda.get_device_properties(0).total_memory
report['cuda_matmul_finite'] = bool(torch.isfinite(b).all())
report['imports'] = {}
for name in ['kimodo', 'motion_correction', 'transformers', 'peft', 'safetensors', 'scipy']:
    module = importlib.import_module(name)
    report['imports'][name] = getattr(module, '__version__', 'imported')
report['model_access'] = {}
for repo in ['nvidia/Kimodo-SMPLX-RP-v1', 'meta-llama/Meta-Llama-3-8B-Instruct']:
    try:
        hf_hub_download(repo, 'config.yaml' if 'Kimodo' in repo else 'config.json')
        report['model_access'][repo] = 'authorized config download passed'
    except Exception as exc:
        report['model_access'][repo] = type(exc).__name__
report['smplx_raw_npz_optional_present'] = (root/'upstream/kimodo/assets/skeletons/smplx22/SMPLX_NEUTRAL.npz').is_file()
report['smplx_blender_asset_present'] = (Path.home()/'.config/blender/4.5/extensions/user_default/smplx_blender_addon/data/smplx_model_lh_20230302.blend').is_file()
(root/'environment_validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
