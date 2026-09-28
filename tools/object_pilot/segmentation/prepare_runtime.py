"""Download authorized SAM3 weights and record the CPU image-API import check."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import time

from huggingface_hub import get_token, hf_hub_download

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', required=True, type=Path)
args = parser.parse_args()
start = time.monotonic()
revision = '3c879f39826c281e95690f02c7821c4de09afae7'
files = {}
for filename in ['sam3.pt', 'config.json']:
    files[filename] = hf_hub_download('facebook/sam3', filename, revision=revision,
                                    local_dir=args.runtime / 'checkpoints', token=get_token())
download_seconds = time.monotonic()-start
# Import checks happen after downloads so a dependency fix does not repeat a large fetch.
from sam3.model_builder import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
import torch
report = {
    'created_utc': datetime.now(timezone.utc).isoformat(), 'python': platform.python_version(),
    'torch': torch.__version__, 'cuda_build': torch.version.cuda,
    'repo': 'facebook/sam3', 'checkpoint_revision': revision, 'files': files,
    'source_revision': (args.runtime / 'source_revision.txt').read_text().strip(),
    'image_api_import': 'passed', 'download_seconds': download_seconds,
    'runtime_scope': 'Dedicated SAM3 Python venv; installed package set is recorded in the environment.',
    'official_readme_python': '>=3.12', 'official_pyproject_python': '>=3.8; includes Python 3.11 classifier',
    'packages': {name: importlib.metadata.version(name) for name in ['sam3', 'numpy', 'timm', 'ftfy', 'iopath']},
}
(args.runtime / 'runtime.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
