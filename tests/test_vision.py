import asyncio
import base64
from io import BytesIO
import json

import httpx
from PIL import Image
import pytest

import vision


def sample_png():
    b = BytesIO()
    Image.new('RGB', (30, 30), color=(120, 150, 190)).save(b, format='PNG')
    return b.getvalue()


def config(monkeypatch):
    monkeypatch.setenv('DOCSPACE_URL', 'https://demo.onlyoffice.example')
    monkeypatch.setenv('DOCSPACE_API_KEY', 'secret-docspace')
    monkeypatch.setenv('MISTRAL_API_KEY', 'secret-mistral')
    monkeypatch.setenv('MISTRAL_MODEL', 'mistral-large-4')
    monkeypatch.setenv('MISTRAL_MAX_TOKENS', '6000')
    monkeypatch.delenv('DOCSPACE_DOWNLOAD_HOSTS', raising=False)


def fake_client(monkeypatch, handle):
    real = httpx.AsyncClient
    monkeypatch.setattr(vision.httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(handle), **kw))


def test_guard(monkeypatch):
    config(monkeypatch)
    vision.ensure_safe_download('https://demo.onlyoffice.example/download?token=abc')
    for url in ['http://demo.onlyoffice.example/file', 'https://127.0.0.1/foo',
                'https://evil.example/', 'https://demo.onlyoffice.example.evil.example/',
                'https://admin:pass@demo.onlyoffice.example/a']:
        with pytest.raises(ValueError):
            vision.ensure_safe_download(url)


def test_docspace_image_download(monkeypatch):
    config(monkeypatch)
    png = sample_png()
    calls = []

    def handle(request):
        calls.append(str(request.url))
        if request.url.path.endswith('/presigneduri'):
            return httpx.Response(200, json={'response': 'https://demo.onlyoffice.example/download/123?key=secret'})
        if request.url.path.endswith('/file/123'):
            assert request.headers['Authorization'] == 'Bearer secret-docspace'
            return httpx.Response(200, json={'response': {'title': 'image.png', 'contentLength': len(png)}})
        if request.url.path == '/download/123':
            return httpx.Response(200, content=png)
        raise AssertionError(request.url)

    fake_client(monkeypatch, handle)
    out, typ = asyncio.run(vision.read_docspace_image(123))
    assert out == png and typ == 'image/png'
    assert len(calls) == 3


def test_mistral_multimodal(monkeypatch):
    config(monkeypatch)
    png = sample_png()
    def handle(request):
        assert request.url.scheme == 'https'
        assert request.url.host == 'api.mistral.ai'
        assert request.url.path == '/v1/chat/completions'
        assert request.headers['Authorization'] == 'Bearer secret-mistral'
        body = json.loads(request.content)
        assert body['model'] == 'mistral-large-4'
        assert body['max_tokens'] == 6000
        assert body['messages'][0]['role'] == 'system'
        assert body['messages'][1]['role'] == 'user'
        assert body['messages'][1]['content'][0]['text'] == 'Que vois-tu ?'
        url = body['messages'][1]['content'][1]['image_url']
        assert isinstance(url, str)
        assert url.startswith('data:image/png;base64,')
        assert base64.b64decode(url.split(',')[1]) == png
        return httpx.Response(200, json={'choices': [{'message': {'content': 'Une image avec un carré.'}}]})
    fake_client(monkeypatch, handle)
    out = asyncio.run(vision.mistral_vision(png, 'image/png', 'Que vois-tu ?'))
    assert 'carré' in out


def test_mistral_text_chunks(monkeypatch):
    config(monkeypatch)
    fake_client(monkeypatch, lambda request: httpx.Response(200, json={'choices': [{'message': {
        'content': [{'type': 'text', 'text': 'Première ligne'}, {'type': 'other', 'x': True},
                    {'type': 'text', 'text': 'Deuxième ligne'}]
    }}]}))
    out = asyncio.run(vision.mistral_vision(sample_png(), 'image/png', 'OCR'))
    assert out == 'Première ligne\nDeuxième ligne'


def test_mistral_auth_error_no_token_leak(monkeypatch):
    config(monkeypatch)
    fake_client(monkeypatch, lambda request: httpx.Response(401, text='secret-mistral should not appear'))
    with pytest.raises(RuntimeError, match='HTTP 401') as err:
        asyncio.run(vision.mistral_vision(sample_png(), 'image/png', 'OCR'))
    assert 'secret-mistral' not in str(err.value)


def test_mistral_empty_output(monkeypatch):
    config(monkeypatch)
    fake_client(monkeypatch, lambda request: httpx.Response(200, json={'choices': [{'message': {'content': ''}}]}))
    with pytest.raises(ValueError, match="n'a pas retourné"):
        asyncio.run(vision.mistral_vision(sample_png(), 'image/png', 'OCR'))
