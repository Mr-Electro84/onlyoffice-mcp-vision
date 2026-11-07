# ONLYOFFICE DocSpace — MCP OCR + Vision avec Mistral Large 4

**Version adaptée à Mistral Studio (API d'inférence Mistral)**. Serveur MCP **lecture seule** qui récupère les pixels d'une image **déjà enregistrée dans DocSpace**, les transmet directement à **Mistral Large 4**, puis renvoie la description et/ou la transcription OCR à un agent ONLYOFFICE. **OpenRouter n'est plus utilisé.**

> ⚠️ Usage individuel / espace privé. L'accès aux fichiers repose sur une **clé API DocSpace unique** : le serveur ne vérifie pas les permissions de chaque utilisateur de l'agent. Ne pas partager ce MCP avec des utilisateurs non approuvés.

## 1. Prérequis

- Instance ONLYOFFICE SaaS avec la fonctionnalité **Serveurs MCP**.
- Clé API ONLYOFFICE avec les droits en lecture nécessaires (`Outils de développement > Clés API`, selon ton interface).
- Clé API **Mistral Studio** avec accès à `mistral-large-4` (et facturation Mistral activée si nécessaire) : https://console.mistral.ai/.
- Serveur Linux ou hébergeur Docker joignable en HTTPS (un certificat valide est nécessaire pour ONLYOFFICE SaaS).

## 2. Différences avec la version OpenRouter

| Avant | Maintenant |
|---|---|
| `OPENROUTER_API_KEY` | `MISTRAL_API_KEY` |
| `OPENROUTER_MODEL=google/gemini-3.8-flash` | `MISTRAL_MODEL=mistral-large-4` |
| `https://openrouter.ai/api/v1/chat/completions` | `https://api.mistral.ai/v1/chat/completions` |
| `image_url: {"url": "data:..."}` | `image_url: "data:..."` |

Les **trois outils MCP et le JSON de connexion ONLYOFFICE restent identiques**. Vision et OCR passent tous les deux par le même modèle multimodal. Cela n'utilise **pas** le moteur OCR spécialisé `mistral-ocr-latest` de Mistral Document AI.

## 3. Configuration

```bash
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Modifier `.env` :

```dotenv
DOCSPACE_URL=https://votre-instance.onlyoffice.com
DOCSPACE_API_KEY=VOTRE_CLE_ONLYOFFICE
MISTRAL_API_KEY=VOTRE_CLE_MISTRAL_STUDIO
MISTRAL_MODEL=mistral-large-4
MISTRAL_MAX_TOKENS=6000
MCP_AUTH_TOKEN=UN_JETON_ALEATOIRE_LONG
DOCSPACE_DOWNLOAD_HOSTS=
```

La clé Mistral Studio **n'est pas** celle de ton compte ONLYOFFICE ni la clé du fournisseur qu'ONLYOFFICE gère en interne : ce MCP utilise ta propre facturation API Mistral.

Si tu migres un déploiement existant, supprime les lignes `OPENROUTER_*` de `.env`, renseigne `MISTRAL_*`, puis reconstruis le conteneur. **Ne publie jamais `.env` ni les clés API.**

## 4. Déployer

```bash
docker compose up -d --build
docker compose logs --tail=100 vision-mcp
```

Le serveur écoute uniquement sur `127.0.0.1:8000`. Un reverse proxy comme Caddy doit exposer une URL HTTPS publique, par exemple `https://mcp.votre-domaine.fr/mcp`. Un exemple de configuration est fourni (`Caddyfile.example`).

Pour tester l'API Mistral *sans DocSpace ni MCP* (test facultatif susceptible d'être facturé), sur une machine avec Python, `pip install -r requirements.txt` puis :

```bash
export MISTRAL_API_KEY='VOTRE_CLE_MISTRAL'
python test_mistral_local.py ./image-test.png
```

Pour tester le serveur MCP en ligne :

```bash
export MCP_AUTH_TOKEN='VOTRE_JETON_MCP'
python test_mcp.py https://mcp.votre-domaine.fr/mcp
```

## 5. Connexion ONLYOFFICE

Dans `Paramètres IA > Serveurs MCP > Modifier la configuration`, fusionner l'entrée suivante avec les serveurs existants :

```json
{
  "mcpServers": {
    "docspace-vision": {
      "type": "http",
      "url": "https://mcp.votre-domaine.fr/mcp",
      "headers": {
        "Authorization": "Bearer VOTRE_JETON_MCP"
      }
    }
  }
}
```

Activer les trois outils : `lister_images_docspace`, `analyser_image_docspace`, `extraire_texte_image_docspace`.

Exemple de requête :

> Utilise `lister_images_docspace` pour trouver `phare.jpg` dans Mes documents. Récupère son véritable `file_id`, puis appelle `analyser_image_docspace` pour expliquer ce que tu vois. Utilise ensuite `extraire_texte_image_docspace` pour transcrire les inscriptions visibles.

Le nom du fichier ou le chemin temporaire d'une pièce jointe dans le chat (`5229394/photo.jpg`) **ne remplace pas** un véritable identifiant `file_id` DocSpace.

## 6. Limitations et sécurité

- Images JPG / PNG / WEBP / GIF **stockées dans DocSpace**, au plus 10 Mio et 20 MP par fichier.
- `lister_images_docspace` montre seulement les 100 premiers fichiers du dossier choisi. Il est possible de lui fournir un identifiant de dossier numérique en `dossier`.
- La clé API DocSpace donne les droits d'un compte technique (elle ne reproduit pas les autorisations individuelles de chaque agent). Limiter impérativement les droits et l'accès au serveur MCP.
- Une URL de téléchargement présignée peut renvoyer vers un domaine distinct. Ajouter **uniquement l'hôte exact vérifié** à `DOCSPACE_DOWNLOAD_HOSTS` si nécessaire. Éviter les domaines non fiables ou internes.
- Les pixels de l'image sont transmis directement au service cloud Mistral : vérifier les conditions de confidentialité et les règles applicables à tes documents.
- Les erreurs de Mistral retournent uniquement le code HTTP (pas le corps contenant potentiellement des informations sensibles).
- `MISTRAL_MAX_TOKENS` (défaut 6000) peut être augmenté jusqu'à 32768 pour un OCR très long, sous réserve des limites du modèle et du compte.
- Les opérations de vision peuvent générer des coûts sur ton compte **Mistral Studio**, séparément du solde IA ONLYOFFICE.
- Vérifier les dépendances et figer les versions avant un usage de production.

## 7. Dépannage

| Erreur | Vérification |
|---|---|
| `401` du serveur MCP | Jeton `MCP_AUTH_TOKEN` invalide ou absent dans le JSON ONLYOFFICE |
| `401/403` côté DocSpace | Clé DocSpace invalide ou permissions insuffisantes |
| `404` côté DocSpace | Fichier inexistant, permissions ou mauvais `file_id` |
| `Hôte de téléchargement non autorisé` | Voir `DOCSPACE_DOWNLOAD_HOSTS` et les redirections HTTPS |
| `Erreur API Mistral HTTP 401` | Clé `MISTRAL_API_KEY` absente/invalide |
| `Erreur API Mistral HTTP 400/404` | Vérifier l'accès au modèle et le format multimodal |
| `Erreur API Mistral HTTP 429` | Quotas / limitation de débit de ton compte Mistral |
| Pas de texte en sortie | Vérifier la limite `MISTRAL_MAX_TOKENS` et les permissions d'accès au modèle |

## 8. Vérification du code (sans accès au compte Mistral)

```bash
pip install -r requirements.txt pytest
pytest -q
```

Les tests utilisent un faux serveur HTTP : ils vérifient le téléchargement DocSpace, le format Base64 des images, la clé Mistral et l'analyse des réponses. Ils n'exécutent **aucun appel réel facturé** à Mistral.

## Sources techniques

- Modèle Mistral Large 4 : https://docs.mistral.ai/models/mistral-large-4-0
- Vision Mistral : https://docs.mistral.ai/inference/conversations/vision
- API Mistral : https://docs.mistral.ai/api
- API DocSpace : https://api.onlyoffice.com/docspace/api-backend/get-started/authentication
- Documentation FastMCP : https://gofastmcp.com/deployment/http
