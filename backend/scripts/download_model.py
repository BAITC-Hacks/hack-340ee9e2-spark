"""Explicit online provisioning. Does not read or upload meeting data."""
import argparse
from pathlib import Path
from huggingface_hub import snapshot_download

parser = argparse.ArgumentParser(description='Скачать публичную модель для последующего локального запуска.')
parser.add_argument('--model',choices=['tiny','base','small','medium','large-v3'],default='small')
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
path=snapshot_download(repo_id='Systran/faster-whisper-'+args.model,
    local_dir=str(args.output), token=False,
    allow_patterns=['model.bin','config.json','tokenizer.json','preprocessor_config.json','vocabulary.*'])
print('Модель сохранена:',path)
print('Укажите эту папку в WHISPER_MODEL_DIR перед запуском backend.')
