"""Read-only remote MCP server for ONE trusted ONLYOFFICE workspace."""
import os
from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from vision import analyze_docspace_image, list_docspace_images, required

# Refuse to start if a secret is missing. Never expose an unauthenticated MCP endpoint.
for key in ("DOCSPACE_URL", "DOCSPACE_API_KEY", "MISTRAL_API_KEY", "MCP_AUTH_TOKEN"):
    required(key)

auth = StaticTokenVerifier(tokens={os.environ["MCP_AUTH_TOKEN"]: {"sub": "onlyoffice-agent", "client_id": "onlyoffice"}})
mcp = FastMCP("DocSpace OCR Vision - Mistral Large 4", auth=auth)

@mcp.tool()
async def lister_images_docspace(dossier: str = "@my") -> list[dict]:
    """Liste les JPG/PNG/WEBP/GIF d'un dossier DocSpace. dossier='@my' pour Mes documents, sinon ID numérique. Première page uniquement. Retourne les file_id à utiliser pour l'analyse."""
    return await list_docspace_images(dossier)

@mcp.tool()
async def analyser_image_docspace(file_id: int, question: str = "Décris l'image et retranscris tous les textes visibles.") -> str:
    """Analyse visuelle et OCR d'une image DEJA ENREGISTREE dans DocSpace, à partir de son véritable file_id numérique. Ne pas utiliser un chemin de pièce jointe du chat."""
    return await analyze_docspace_image(file_id, question)

@mcp.tool()
async def extraire_texte_image_docspace(file_id: int) -> str:
    """OCR fidèle: extrait le texte d'un fichier image DEJA ENREGISTRE dans DocSpace avec son vrai file_id numérique."""
    return await analyze_docspace_image(file_id, "Retranscris fidèlement tout texte visible. Respecte les lignes et tableaux. Indique [illisible] plutôt que d'inventer.")

app = mcp.http_app(path="/mcp", stateless_http=True)
