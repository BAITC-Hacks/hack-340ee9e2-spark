"""Repository integration regression tests. Team adapter calls here are fake."""
from pathlib import Path
import os
import tempfile
from types import SimpleNamespace
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
        paths = []
        def fake_team(path):
            paths.append(Path(path))
            self.assertTrue(Path(path).exists())
            return {'language':'ru', 'full_text':'Проверьте договор.', 'segments':[
                {'speaker':'Real speaker label', 'start':2.25, 'end':5.75, 'text':'Проверьте договор.'}],
                'diarization_available':True}
        with tempfile.TemporaryDirectory() as folder:
            for filename in ('model.bin','config.json','tokenizer.json'):
                (Path(folder)/filename).touch()
            with patch.dict(os.environ, {'WHISPER_MODEL_PATH':folder}), patch.dict('sys.modules', {
                'ai.transcription':SimpleNamespace(transcribe_audio=fake_team),
                'onnxruntime':SimpleNamespace(disable_telemetry_events=lambda:None),
            }):
                app.dependency_overrides[get_transcriber] = lambda:TeamTranscriber()
                response = self.client.post('/analyze-audio', files={'file':('test.mp3',b'test')})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data['diarization_available'])
        self.assertEqual(data['protocol']['transcript'][0]['start'], 2.25)
        self.assertEqual(data['protocol']['transcript'][0]['speaker'], 'Real speaker label')
        self.assertIsNone(data['protocol']['action_items'][0]['responsible'])
        self.assertTrue(all(not path.exists() for path in paths))

    def test_team_language_override_is_not_silently_ignored(self):
        app.dependency_overrides[get_transcriber] = lambda:TeamTranscriber()
        response = self.client.post('/transcribe?language=ru', files={'file':('test.mp3',b'test')})
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
