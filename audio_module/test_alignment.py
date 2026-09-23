"""Deterministic synthetic tests, not evidence that the model has run."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .align import align_segments
from .diarize import add_diarization, COMMUNITY_FILES


def turn(start, end, speaker='SPEAKER_00'):
    return {'start': start, 'end': end, 'speaker': speaker}


class AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.segments = [{'start': 0, 'end': 10, 'text': 'Синтетический тест қазақша', 'speaker': None}]

    def check(self, turns, speaker, reason):
        original = deepcopy(self.segments)
        result, diagnostics = align_segments(self.segments, turns)
        self.assertEqual(result[0]['speaker'], speaker)
        self.assertEqual(diagnostics[0]['reason'], reason)
        self.assertEqual(self.segments, original)
        for before, after in zip(original, result):
            for key in ('start', 'end', 'text'):
                self.assertEqual(before[key], after[key])

    def test_one_speaker(self):
        self.check([turn(0, 10)], 'SPEAKER_00', 'assigned')

    def test_change_inside_segment(self):
        self.check([turn(0, 5), turn(5, 10, 'SPEAKER_01')], None, 'speaker_change_within_segment')

    def test_change_at_segment_boundary(self):
        self.segments = [dict(self.segments[0], end=5), dict(self.segments[0], start=5)]
        result, _ = align_segments(self.segments, [turn(0, 5), turn(5, 10, 'SPEAKER_01')])
        self.assertEqual([s['speaker'] for s in result], ['SPEAKER_00', 'SPEAKER_01'])

    def test_overlapping_speech(self):
        self.check([turn(0, 7), turn(5, 10, 'SPEAKER_01')], None, 'overlapping_speech')

    def test_no_match(self):
        self.check([turn(10, 15)], None, 'no_matching_speech')

    def test_low_coverage(self):
        self.check([turn(0, 2)], None, 'insufficient_coverage')

    def test_duplicate_turns_do_not_inflate_coverage(self):
        self.check([turn(0, 3), turn(0, 3)], None, 'insufficient_coverage')

    def test_invalid_interval(self):
        with self.assertRaises(ValueError):
            align_segments(self.segments, [turn(1, float('nan'))])

    def test_human_name_rejected(self):
        with self.assertRaises(ValueError):
            align_segments(self.segments, [turn(0, 10, 'Aida')])

    def test_missing_model_preserves_transcript(self):
        original = {'text': 'Тест', 'segments': self.segments,
                    'processing': {'processed_start_seconds': 0, 'processed_end_seconds': 10}}
        before = deepcopy(original)
        with tempfile.TemporaryDirectory() as directory:
            result = add_diarization('missing.mp3', original, model_dir=directory)
        self.assertEqual(result['diarization']['status'], 'unavailable')
        self.assertEqual(result['diarization']['code'], 'model_missing')
        self.assertEqual(result['segments'], original['segments'])
        self.assertEqual(original, before)

    def test_process_timeout_preserves_transcript(self):
        import subprocess
        import sys
        import numpy as np
        original = {'text': 'Тест', 'segments': self.segments,
                    'processing': {'processed_start_seconds': 0, 'processed_end_seconds': 10}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in COMMUNITY_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'synthetic fixture, not a model')
            audio = root / 'test.mp3'
            audio.write_bytes(b'synthetic fixture')
            with patch('audio_module.transcribe._decode_mp3', return_value=(np.zeros(160000), 10, False)), \
                 patch('audio_module.diarize.subprocess.run', side_effect=subprocess.TimeoutExpired('worker', 1)):
                result = add_diarization(audio, original, model_dir=root, python_executable=sys.executable)
        self.assertEqual(result['diarization']['code'], 'timeout')
        self.assertEqual(result['segments'], original['segments'])

    def test_process_failure_preserves_transcript(self):
        import subprocess
        import sys
        import numpy as np
        original = {'text': 'Тест', 'segments': self.segments,
                    'processing': {'processed_start_seconds': 0, 'processed_end_seconds': 10}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in COMMUNITY_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'synthetic fixture, not a model')
            audio = root / 'test.mp3'
            audio.write_bytes(b'synthetic fixture')
            with patch('audio_module.transcribe._decode_mp3', return_value=(np.zeros(160000), 10, False)), \
                 patch('audio_module.diarize.subprocess.run', return_value=subprocess.CompletedProcess('worker', 1)):
                result = add_diarization(audio, original, model_dir=root, python_executable=sys.executable)
        self.assertEqual(result['diarization']['code'], 'process_failed')
        self.assertEqual(result['segments'], original['segments'])

    def test_real_worker_rejects_non_community_config(self):
        import json
        import subprocess
        from .diarize import DEFAULT_DIARIZATION_PYTHON, MODULE_DIR, offline_environment
        import os
        if not DEFAULT_DIARIZATION_PYTHON.is_file():
            self.skipTest('Separate environment not installed')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in COMMUNITY_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'synthetic fixture, not a model')
            (root / 'config.yaml').write_text('pipeline:\n  name: forbidden.cloud.Pipeline\n')
            output = root / 'result.json'
            env = os.environ.copy()
            env.update(offline_environment())
            process = subprocess.run([
                str(DEFAULT_DIARIZATION_PYTHON), '-m', 'audio_module.diarize_worker',
                '--model-dir', str(root), '--waveform', str(root/'absent.npy'),
                '--output', str(output)], cwd=MODULE_DIR.parent, env=env,
                capture_output=True, timeout=30)
            self.assertEqual(process.returncode, 1)
            self.assertEqual(json.loads(output.read_text())['code'], 'invalid_model')


if __name__ == '__main__':
    unittest.main()
