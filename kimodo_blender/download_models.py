"""Download official model assets using the local Hugging Face login (huggingface-cli login or HF_TOKEN)."""
import json
import os
import time
from pathlib import Path

from huggingface_hub import snapshot_download

root = Path(os.environ['KIMODO_ROOT'])
status_file = root/'model_download_status.json'
completed = []
jobs = [
    ('nvidia/Kimodo-SMPLX-RP-v1', str(root/'checkpoints/Kimodo-SMPLX-RP-v1')),
    ('meta-llama/Meta-Llama-3-8B-Instruct', None),
    ('McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp', None),
    ('McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised', None),
]
for repo, local in jobs:
    status_file.write_text(json.dumps({'status':'downloading','current':repo,'completed':completed,'updated_unix':time.time()},indent=2))
    print('Downloading', repo, flush=True)
    try:
        path = snapshot_download(repo, local_dir=local, cache_dir=os.environ['HF_HUB_CACHE'],
            allow_patterns=['*.json','*.yaml','*.npy','*.npz','*.safetensors','tokenizer.model','LICENSE*','NOTICE*','README.md','USE_POLICY.md'],max_workers=4)
    except Exception as exc:
        status_file.write_text(json.dumps({'status':'failed','current':repo,'completed':completed,'error_type':type(exc).__name__},indent=2))
        raise
    completed.append({'repo':repo,'path':path})
status_file.write_text(json.dumps({'status':'complete','completed':completed,'updated_unix':time.time()},indent=2))
print('MODEL_DOWNLOADS_COMPLETE', flush=True)
