"""End-to-end API check. Start uvicorn first. Generated files stay outside the repo."""
import argparse
from io import BytesIO
import json
from pathlib import Path
from tempfile import mkdtemp
from zipfile import ZipFile
import httpx

parser=argparse.ArgumentParser()
parser.add_argument('--url',default='http://127.0.0.1:8000')
parser.add_argument('--audio',type=Path)
args=parser.parse_args()
with httpx.Client(base_url=args.url,timeout=600,trust_env=False) as client:
    result=client.get('/health'); result.raise_for_status()
    assert result.json()=={'status':'ok'}
    if args.audio:
        with args.audio.open('rb') as source:
            result=client.post('/analyze-audio',files={'file':(args.audio.name,source)})
        result.raise_for_status()
        data=result.json()
        for warning in data['warnings']: print('Предупреждение:',warning)
        protocol=data['protocol']
    else:
        sample=Path(__file__).resolve().parents[2]/'tests/sample_transcript.txt'
        result=client.post('/analyze',json={'text':sample.read_text(encoding='utf-8')})
        result.raise_for_status()
        protocol=result.json()
        assert [(i['responsible'],i['deadline']) for i in protocol['action_items']]==[
            ('Гульмира Сериковна','15 октября'),('Тимур Болатович','30 сентября'),('Айнур Каировна',None)]
    result=client.post('/export-docx',json=protocol); result.raise_for_status()
    assert result.headers['content-type']=='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    assert ZipFile(BytesIO(result.content)).testzip() is None
    folder=Path(mkdtemp(prefix='hackalem-check-'))
    (folder/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'protocol.docx').write_bytes(result.content)
    print('API и DOCX проверены. Файлы:',folder)
    print('Поручений:',len(protocol['action_items']))
    print('Откройте DOCX и проверьте содержание; успешный HTTP не доказывает полноту анализа.')
