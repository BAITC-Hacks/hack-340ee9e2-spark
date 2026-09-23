"""Repository integration regression tests. Team adapter calls here are fake."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.main import app
from backend.services.audio import TeamTranscriber, LocalWhisperTranscriber, get_transcriber
from backend.services.protocol_analyzer import analyze_transcript


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.addCleanup(app.dependency_overrides.clear)

    def test_conflicting_deadlines_are_unknown(self):
        task = analyze_transcript('Иван, подготовьте отчет до пятницы или до среды.')['action_items'][0]
        self.assertIsNone(task['deadline'])
        self.assertIn('до пятницы или до среды', task['source_fragment'])

    def test_explicit_let_assignment_from_real_recognized_wording(self):
        source = 'Хорошо, пусть Ерлан до конца недели подготовит претензию, а вы параллельно за две недели проверьте договор.'
        tasks = analyze_transcript(source)['action_items']
        self.assertEqual(len(tasks), 2)
        self.assertEqual((tasks[0]['text'], tasks[0]['responsible'], tasks[0]['deadline']),
                         ('Подготовить претензию', 'Ерлан', 'конца недели'))
        self.assertIsNone(tasks[1]['responsible'])
        self.assertEqual(tasks[1]['deadline'], 'за две недели')

    def test_future_statement_without_directive_is_not_assignment(self):
        for source in ('Ерлан подготовит претензию.', 'Подготовит отчет.',
                       'Если будет время, пусть Ерлан подготовит претензию.'):
            self.assertEqual(analyze_transcript(source)['action_items'], [])

    def test_unknown_owner_label_and_dative_weekday(self):
        task = analyze_transcript('Представьте отчет к среде — ответственный не определено.')['action_items'][0]
        self.assertIsNone(task['responsible'])
        self.assertEqual(task['deadline'], 'среде')

    def test_team_contract_preserves_metadata_without_owner_inference(self):
        original = {'language': 'ru', 'text': 'Проверьте договор.', 'segments': [
            {'speaker': None, 'start': 2.25, 'end': 5.75, 'text': 'Проверьте договор.'}],
            'processing': {'processed_start_seconds': 0.0, 'processed_end_seconds': 60.0}}
        order = []
        def fake_asr(path, **kwargs):
            self.assertTrue(path.exists())
            self.assertEqual(kwargs['language'], 'ru')
            self.assertEqual(kwargs['max_seconds'], 60)
            order.append('asr')
            return original
        def fake_diarization(path, transcript, **kwargs):
            self.assertIs(transcript, original)
            order.append('diarization')
            return {**original, 'segments': [{**original['segments'][0], 'speaker': 'SPEAKER_00'}],
                    'diarization': {'status': 'ok'}}
        from backend.main import build_protocol
        def analyze(request):
            order.append('analysis')
            return build_protocol(request)
        with patch('audio_module.transcribe_mp3', side_effect=fake_asr), \
             patch('audio_module.diarize.add_diarization', side_effect=fake_diarization), \
             patch('backend.main.build_protocol', side_effect=analyze):
            response = self.client.post('/analyze-audio?language=ru&max_seconds=60',
                files={'file': ('test.mp3', b'test')})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(order, ['asr', 'diarization', 'analysis'])
        self.assertEqual(data['text'], original['text'])
        self.assertTrue(data['diarization_available'])
        self.assertEqual(data['protocol']['transcript'][0],
                         {**original['segments'][0], 'speaker': 'SPEAKER_00'})
        self.assertIsNone(data['protocol']['action_items'][0]['responsible'])

    def test_unavailable_and_failed_diarization_preserve_transcript(self):
        original = {'language': 'ru', 'text': 'Проверьте договор.', 'segments': [
            {'speaker': None, 'start': 1.0, 'end': 3.0, 'text': 'Проверьте договор.'}]}
        for status in ('unavailable', 'failed', 'not_run', 'no_speech_detected', 'exception'):
            with self.subTest(status=status):
                with patch('audio_module.transcribe_mp3', return_value=original), \
                     patch('audio_module.diarize.add_diarization',
                           side_effect=RuntimeError('PRIVATE') if status == 'exception' else None,
                           return_value={**original, 'diarization': {'status': status}}):
                    response = self.client.post('/analyze-audio', files={'file': ('a.mp3', b'x')})
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertFalse(result['diarization_available'])
                self.assertEqual(result['protocol']['transcript'], original['segments'])
                self.assertEqual(result['text'], original['text'])
                self.assertNotIn('PRIVATE', response.text)
                self.assertTrue(result['warnings'])

    def test_ok_diarization_with_all_segments_ambiguous(self):
        original = {'text': 'Проверьте договор.', 'segments': [
            {'speaker': None, 'start': 1.0, 'end': 3.0, 'text': 'Проверьте договор.'}]}
        with patch('audio_module.transcribe_mp3', return_value=original), \
             patch('audio_module.diarize.add_diarization', return_value={**original,
                'diarization': {'status': 'ok', 'assignments': [
                    {'segment_index': 0, 'reason': 'speaker_change_within_segment'}]}}):
            response = self.client.post('/analyze-audio', files={'file': ('a.mp3', b'x')})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['diarization_available'])
        self.assertIsNone(response.json()['protocol']['transcript'][0]['speaker'])

    def test_static_frontend_and_private_paths(self):
        for path in ('/', '/app.js', '/styles.css'):
            self.assertEqual(self.client.get(path).status_code, 200)
        for path in ('/audio_module/results/meeting-1-first-60s.json', '/.vscode/settings.json',
                     '/backend/main.py', '/api/meetings'):
            self.assertEqual(self.client.get(path).status_code, 404)
        script = self.client.get('/app.js').text
        self.assertIn('window.location.origin', script)
        self.assertNotIn('/api/meetings', script)

    def test_invalid_prefix_limit(self):
        for limit in (0, 601):
            response = self.client.post(f'/analyze-audio?max_seconds={limit}',
                files={'file': ('a.mp3', b'x')})
            self.assertEqual(response.status_code, 422)

    def test_missing_tokenizer_prevents_any_model_import(self):
        with tempfile.TemporaryDirectory() as folder:
            for filename in ('model.bin','config.json'):
                (Path(folder)/filename).touch()
            with patch.dict(os.environ, {'WHISPER_MODEL_DIR':folder, 'WHISPER_MODEL_PATH':''}):
                app.dependency_overrides[get_transcriber] = lambda:LocalWhisperTranscriber()
                response = self.client.post('/transcribe', files={'file':('test.mp3',b'test')})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.client.post('/analyze', json={'text':'Проверьте договор.'}).status_code, 200)

    def test_audio_limit_without_content_length_never_calls_adapter(self):
        with patch('backend.main.MAX_UPLOAD_BYTES', 4), patch('backend.main._transcribe') as transcribe:
            chunks = (b'x'*40000 for _ in range(2))
            response = self.client.post('/transcribe', content=chunks,
                                        headers={'Content-Type':'multipart/form-data; boundary=test'})
            self.assertEqual(response.status_code, 413)
            transcribe.assert_not_called()


if __name__ == '__main__':
    unittest.main()
