"""Test facultatif facturé : python test_mistral_local.py /chemin/image.png"""
import asyncio
from io import BytesIO
from pathlib import Path
import sys
from PIL import Image
from vision import mistral_vision, VALID_FORMATS, MAX_IMAGE_BYTES


async def main(path: Path) -> None:
    if not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("Fichier introuvable ou > 10 Mio")
    data = path.read_bytes()
    with Image.open(BytesIO(data)) as im:
        fmt = im.format
        im.verify()
    if fmt not in VALID_FORMATS:
        raise ValueError("Format pris en charge : JPG, PNG, WEBP ou GIF")
    print(await mistral_vision(data, VALID_FORMATS[fmt], "Décris précisément cette image et lis les textes visibles."))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage : python test_mistral_local.py /chemin/image.png")
    asyncio.run(main(Path(sys.argv[1])))
