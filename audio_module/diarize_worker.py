"""Internal worker: audio only, local Community-1 only, no transcript or token."""

import argparse
import json
import os
from pathlib import Path
import sys

from .diarize import COMMUNITY_FILES, offline_environment

# Must precede all third-party imports, including PyTorch/pyannote/Hub.
os.environ.update(offline_environment())


def _deny_network(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo'):
        raise PermissionError('network_blocked')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-dir', type=Path, required=True)
    parser.add_argument('--waveform', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.addaudithook(_deny_network)
    code = 'inference_failed'
    try:
        model = args.model_dir.resolve()
        if any(not (model / name).is_file() for name in COMMUNITY_FILES):
            raise FileNotFoundError
        import yaml
        config = yaml.safe_load((model / 'config.yaml').read_text())
        if config.get('pipeline', {}).get('name') != 'pyannote.audio.pipelines.SpeakerDiarization':
            code = 'invalid_model'
            raise ValueError
        import numpy as np
        import torch
        from pyannote.audio import Pipeline

        audio = np.load(args.waveform, allow_pickle=False)
        if audio.ndim != 1 or not 0 < len(audio) <= 600 * 16000 or not np.isfinite(audio).all():
            raise ValueError
        torch.set_num_threads(4)
        pipeline = Pipeline.from_pretrained(str(model), token=False)
        if pipeline is None:
            code = 'invalid_model'
            raise ValueError
        pipeline.to(torch.device('cpu'))
        with torch.inference_mode():
            output = pipeline({'waveform': torch.from_numpy(audio).float().unsqueeze(0),
                               'sample_rate': 16000})
        regular = list(output.speaker_diarization)
        exclusive = list(output.exclusive_speaker_diarization)
        # Technical labels assigned in order of first appearance, shared by both tracks.
        mapping = {}
        for turn, speaker in sorted([*regular, *exclusive], key=lambda x: (x[0].start, str(x[1]))):
            if speaker not in mapping:
                mapping[speaker] = f'SPEAKER_{len(mapping):02d}'
        duration = len(audio) / 16000

        def serialize(track):
            rows = []
            for turn, speaker in track:
                start = round(max(0.0, float(turn.start)), 6)
                end = round(min(duration, float(turn.end)), 6)
                if end > start:
                    rows.append({'start': start, 'end': end, 'speaker': mapping[speaker]})
            return sorted(rows, key=lambda row: (row['start'], row['end'], row['speaker']))

        payload = {'status': 'ok', 'turns': serialize(regular), 'exclusive_turns': serialize(exclusive)}
    except ModuleNotFoundError:
        payload = {'status': 'failed', 'code': 'missing_dependency'}
    except PermissionError:
        payload = {'status': 'failed', 'code': 'network_blocked'}
    except Exception:
        payload = {'status': 'failed', 'code': code}
    args.output.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    return 0 if payload['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
