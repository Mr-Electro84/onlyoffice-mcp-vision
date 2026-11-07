"""ONLYOFFICE DocSpace -> Mistral Large 4 via Mistral API (no secrets logged)."""
from __future__ import annotations

import base64
from io import BytesIO
import os
from urllib.parse import urlparse

import httpx
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 10 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 20_000_000
VALID_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Variable d'environnement manquante: {name}")
    return value


def docspace_origin() -> str:
    raw = required("DOCSPACE_URL").rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/"):
        raise ValueError("DOCSPACE_URL doit être une origine HTTPS, sans chemin ni identifiants")
    return raw


def allowed_download_hosts() -> set[str]:
    # Exact hosts only: never allow arbitrary domains or wildcard suffixes.
    portal_host = urlparse(docspace_origin()).hostname
    extra = os.environ.get("DOCSPACE_DOWNLOAD_HOSTS", "")
    return {portal_host, *(s.strip().lower() for s in extra.split(",") if s.strip())}


def ensure_safe_download(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in allowed_download_hosts():
        raise ValueError("Hôte de téléchargement non autorisé. Voir DOCSPACE_DOWNLOAD_HOSTS.")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("URL de téléchargement non autorisée")


def unwrap(data):
    """ONLYOFFICE frequently returns {response: ...}."""
    if isinstance(data, dict) and "response" in data:
        return data["response"]
    return data


async def read_docspace_image(file_id: int) -> tuple[bytes, str]:
    if not isinstance(file_id, int) or isinstance(file_id, bool) or file_id <= 0:
        raise ValueError("file_id doit être un identifiant numérique DocSpace positif")
    origin = docspace_origin()
    headers = {"Authorization": f"Bearer {required('DOCSPACE_API_KEY')}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10), follow_redirects=False) as client:
        info_res = await client.get(f"{origin}/api/2.0/files/file/{file_id}", headers=headers)
        info_res.raise_for_status()
        info = unwrap(info_res.json())
        if not isinstance(info, dict):
            raise ValueError("Réponse de métadonnées DocSpace inattendue")
        title = str(info.get("title", ""))
        if title and not title.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            raise ValueError("Le fichier n'est pas une image JPG/PNG/WEBP/GIF")
        size = info.get("pureContentLength", info.get("contentLength", 0))
        try:
            if int(size) > MAX_IMAGE_BYTES:
                raise ValueError("Image trop volumineuse (10 Mio maximum)")
        except (TypeError, ValueError) as exc:
            if "volumineuse" in str(exc):
                raise

        url_res = await client.get(f"{origin}/api/2.0/files/file/{file_id}/presigneduri", headers=headers)
        url_res.raise_for_status()
        signed = unwrap(url_res.json())
        if not isinstance(signed, str):
            raise ValueError("Réponse presigneduri invalide: URL attendue")
        url = signed
        for _ in range(4):
            ensure_safe_download(url)
            async with client.stream("GET", url, headers={"Accept": "image/*, application/octet-stream"}) as stream:
                if stream.status_code in (301, 302, 303, 307, 308):
                    location = stream.headers.get("location")
                    if not location:
                        raise ValueError("Redirection sans URL")
                    from urllib.parse import urljoin
                    url = urljoin(url, location)
                    continue
                stream.raise_for_status()
                data = bytearray()
                async for chunk in stream.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_IMAGE_BYTES:
                        raise ValueError("Image téléchargée trop volumineuse (10 Mio maximum)")
                break
        else:
            raise ValueError("Trop de redirections de téléchargement")

    try:
        with Image.open(BytesIO(data)) as im:
            if im.width * im.height > 20_000_000:
                raise ValueError("Image trop grande (20 mégapixels maximum)")
            fmt = im.format
            im.verify()
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError) as exc:
        raise ValueError("Les données récupérées ne sont pas une image valide") from exc
    if fmt not in VALID_FORMATS:
        raise ValueError("Format d'image non pris en charge")
    return bytes(data), VALID_FORMATS[fmt]


async def list_docspace_images(folder: str = "@my") -> list[dict]:
    if folder != "@my" and (not folder.isdecimal() or int(folder) <= 0):
        raise ValueError("folder doit être @my ou un identifiant numérique de dossier")
    origin = docspace_origin()
    headers = {"Authorization": f"Bearer {required('DOCSPACE_API_KEY')}", "Accept": "application/json"}
    path = f"/api/2.0/files/{folder}"
    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.get(origin + path, headers=headers, params={"count": 100, "startIndex": 0})
        res.raise_for_status()
        payload = unwrap(res.json())
    if not isinstance(payload, dict):
        raise ValueError("Réponse de liste DocSpace inattendue")
    items = []
    for file in payload.get("files", []):
        if not isinstance(file, dict):
            continue
        name = str(file.get("title", ""))
        if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            items.append({"file_id": file.get("id"), "nom": name})
    return items


async def mistral_vision(image: bytes, mime: str, instruction: str) -> str:
    """Send the image bytes to Mistral's official cloud inference API.

    Mistral Chat Completions accepts image_url as a *string* containing a
    data:image/...;base64,... URL (not the OpenRouter object {"url": ...}).
    """
    if mime not in VALID_FORMATS.values():
        raise ValueError("Type MIME d'image non pris en charge")
    if not image or len(image) > MAX_IMAGE_BYTES:
        raise ValueError("Image vide ou trop volumineuse")
    model = os.getenv("MISTRAL_MODEL", "mistral-large-4").strip()
    if not model:
        raise ValueError("MISTRAL_MODEL ne doit pas être vide")
    max_tokens = int(os.getenv("MISTRAL_MAX_TOKENS", "6000"))
    if not 1 <= max_tokens <= 32768:
        raise ValueError("MISTRAL_MAX_TOKENS doit être compris entre 1 et 32768")
    if not instruction.strip():
        instruction = "Décris cette image en français et transcris fidèlement son texte, s'il y en a."

    data_url = f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": (
                "Tu es un assistant OCR et Vision. Réponds en français. "
                "Ne devine jamais les caractères illisibles, signale-les par [illisible]. "
                "Distingue les observations de tes interprétations."
            )},
            {"role": "user", "content": [
                {"type": "text", "text": instruction[:4000]},
                {"type": "image_url", "image_url": data_url},
            ]},
        ],
        "max_tokens": max_tokens,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0), follow_redirects=False) as client:
        res = await client.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {required('MISTRAL_API_KEY')}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=body,
        )
        # Deliberately avoid including response bodies, image data or API keys in errors.
        if res.status_code >= 400:
            raise RuntimeError(f"Erreur API Mistral HTTP {res.status_code}; vérifier la clé, le modèle et les quotas")
        response = res.json()

    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Réponse inattendue de l'API Mistral (choices/message/content)") from exc

    if isinstance(content, str):
        result = content
    elif isinstance(content, list):
        result = "\n".join(
            part["text"] for part in content
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        )
    else:
        result = ""
    if not result.strip():
        raise ValueError("Mistral n'a pas retourné de texte d'analyse")
    return result


async def analyze_docspace_image(file_id: int, instruction: str) -> str:
    data, mime = await read_docspace_image(file_id)
    return await mistral_vision(data, mime, instruction)
