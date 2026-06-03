"""
PlanetDiag - Générateur de rapport HTML pour analyse Mistral
Convertit l'analyse Mistral en rapport HTML élégant.
"""

import html
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Palette Ghost Protocol (depuis main.py)
BG        = "#030810"
SURFACE   = "#0a1628"
SURFACE2  = "#122040"
FG        = "#b8d4e8"
FG_DIM    = "#6a9ab8"
FG_MUTED  = "#3a5a78"
ACCENT    = "#00d4ff"
PURPLE    = "#9d50ff"
GREEN     = "#00ff9d"
RED       = "#ff2d55"
YELLOW    = "#ffb730"


# Inline : appliqué APRÈS échappement HTML, uniquement sur du texte (jamais sur du code fence).
# On ne touche pas aux underscores : ils sont trop fréquents dans les noms de services,
# clés JSON, chemins… et provoqueraient des faux positifs d'italique.
_RE_INLINE_CODE = re.compile(r'`([^`]+)`')
_RE_BOLD        = re.compile(r'\*\*([^*]+)\*\*')
_RE_ITALIC      = re.compile(r'(?<![\w*])\*([^*\n]+)\*(?![\w*])')
_RE_HEADING     = re.compile(r'^(#{1,6})\s+(.*)$')
_RE_ULITEM      = re.compile(r'^[-*+]\s+(.*)$')
_RE_OLITEM      = re.compile(r'^\d+\.\s+(.*)$')


def _inline(escaped_text: str) -> str:
    """Applique le formatage inline (code, gras, italique) sur du texte DÉJÀ échappé."""
    escaped_text = _RE_INLINE_CODE.sub(r'<code>\1</code>', escaped_text)
    escaped_text = _RE_BOLD.sub(r'<strong>\1</strong>', escaped_text)
    escaped_text = _RE_ITALIC.sub(r'<em>\1</em>', escaped_text)
    return escaped_text


def _markdown_to_html(markdown_text: str) -> str:
    """
    Convertit le markdown en HTML via un parseur ligne par ligne.
    Gère : blocs de code ```fences```, titres #..######, listes ordonnées et
    non ordonnées, paragraphes et inline (code/gras/italique).
    Pas de dépendance externe. Tout le texte est échappé HTML (anti-XSS).
    """
    lines = markdown_text.replace('\r\n', '\n').split('\n')
    out: list[str] = []
    list_type: Optional[str] = None   # 'ul' | 'ol' | None
    in_code = False
    code_buf: list[str] = []
    para_buf: list[str] = []

    def flush_para():
        if para_buf:
            joined = '<br>'.join(_inline(html.escape(l)) for l in para_buf)
            out.append(f'<p>{joined}</p>')
            para_buf.clear()

    def close_list():
        nonlocal list_type
        if list_type:
            out.append(f'</{list_type}>')
            list_type = None

    for raw in lines:
        stripped = raw.strip()

        # Bascule de bloc de code ```
        if stripped.startswith('```'):
            if in_code:
                out.append('<pre><code>' + html.escape('\n'.join(code_buf)) + '</code></pre>')
                code_buf.clear()
                in_code = False
            else:
                flush_para(); close_list()
                in_code = True
            continue
        if in_code:
            code_buf.append(raw)
            continue

        # Ligne vide → ferme le paragraphe / la liste courante
        if not stripped:
            flush_para(); close_list()
            continue

        # Titres
        m = _RE_HEADING.match(stripped)
        if m:
            flush_para(); close_list()
            level = len(m.group(1))
            out.append(f'<h{level}>{_inline(html.escape(m.group(2)))}</h{level}>')
            continue

        # Liste non ordonnée
        m = _RE_ULITEM.match(stripped)
        if m:
            flush_para()
            if list_type != 'ul':
                close_list(); out.append('<ul>'); list_type = 'ul'
            out.append(f'<li>{_inline(html.escape(m.group(1)))}</li>')
            continue

        # Liste ordonnée
        m = _RE_OLITEM.match(stripped)
        if m:
            flush_para()
            if list_type != 'ol':
                close_list(); out.append('<ol>'); list_type = 'ol'
            out.append(f'<li>{_inline(html.escape(m.group(1)))}</li>')
            continue

        # Ligne de paragraphe ordinaire
        close_list()
        para_buf.append(stripped)

    # Vidange finale (fichier se terminant sans ligne vide)
    if in_code:
        out.append('<pre><code>' + html.escape('\n'.join(code_buf)) + '</code></pre>')
    flush_para()
    close_list()

    return '\n'.join(out)


def _get_css() -> str:
    """Retourne le CSS personnalisé pour le rapport Mistral."""
    return f"""
    * {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }}

    html, body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        background-color: {BG};
        color: {FG};
        line-height: 1.6;
    }}

    body {{
        padding: 2rem;
        max-width: 1000px;
        margin: 0 auto;
    }}

    header {{
        border-bottom: 2px solid {ACCENT};
        padding-bottom: 2rem;
        margin-bottom: 2rem;
    }}

    h1, h2, h3, h4, h5, h6 {{
        color: {ACCENT};
        margin-top: 1.5rem;
        margin-bottom: 0.75rem;
        font-weight: 600;
    }}

    h1 {{
        font-size: 2.5rem;
        margin-bottom: 0.5rem;
    }}

    h2 {{
        font-size: 1.8rem;
        color: {PURPLE};
        border-bottom: 1px solid {SURFACE2};
        padding-bottom: 0.5rem;
    }}

    h3 {{
        font-size: 1.4rem;
    }}

    h4, h5, h6 {{
        color: {FG_DIM};
    }}

    p {{
        margin-bottom: 1rem;
        text-align: justify;
    }}

    strong {{
        color: {ACCENT};
        font-weight: 600;
    }}

    em {{
        color: {YELLOW};
        font-style: italic;
    }}

    code {{
        background-color: {SURFACE2};
        color: {GREEN};
        padding: 0.2rem 0.6rem;
        border-radius: 4px;
        font-family: "Consolas", "Courier New", monospace;
        font-size: 0.95rem;
    }}

    pre {{
        background-color: {SURFACE};
        border-left: 3px solid {ACCENT};
        padding: 1rem;
        border-radius: 4px;
        overflow-x: auto;
        margin: 1rem 0;
    }}

    pre code {{
        background-color: transparent;
        color: {GREEN};
        padding: 0;
        border-radius: 0;
    }}

    ul, ol {{
        margin: 1rem 0;
        padding-left: 2rem;
    }}

    li {{
        margin-bottom: 0.5rem;
        color: {FG};
    }}

    li strong {{
        color: {ACCENT};
    }}

    .meta {{
        background-color: {SURFACE};
        padding: 1.5rem;
        border-radius: 8px;
        margin: 2rem 0;
        border-left: 3px solid {PURPLE};
    }}

    .meta p {{
        margin-bottom: 0.5rem;
        color: {FG_DIM};
    }}

    .section {{
        background-color: {SURFACE};
        padding: 1.5rem;
        border-radius: 8px;
        margin: 2rem 0;
        border-left: 3px solid {ACCENT};
    }}

    .section h2 {{
        border-bottom: none;
        margin-top: 0;
        padding-bottom: 0;
    }}

    footer {{
        border-top: 1px solid {SURFACE2};
        padding-top: 2rem;
        margin-top: 3rem;
        color: {FG_MUTED};
        font-size: 0.9rem;
        text-align: center;
    }}

    a {{
        color: {ACCENT};
        text-decoration: none;
    }}

    a:hover {{
        text-decoration: underline;
        color: {PURPLE};
    }}

    table {{
        width: 100%;
        border-collapse: collapse;
        margin: 1rem 0;
    }}

    th, td {{
        border: 1px solid {SURFACE2};
        padding: 0.75rem;
        text-align: left;
    }}

    th {{
        background-color: {SURFACE2};
        color: {ACCENT};
        font-weight: 600;
    }}

    tr:nth-child(even) {{
        background-color: {SURFACE2};
    }}

    blockquote {{
        border-left: 3px solid {PURPLE};
        padding-left: 1rem;
        margin: 1rem 0;
        color: {FG_DIM};
        font-style: italic;
    }}

    .timestamp {{
        color: {FG_MUTED};
        font-size: 0.85rem;
    }}
    """


def generate_mistral_report(
    mistral_analysis: str,
    machine_name: str,
    output_dir: Path,
) -> Path:
    """
    Génère un rapport HTML à partir de l'analyse Mistral.

    Args:
        mistral_analysis: Texte de l'analyse Mistral
        machine_name: Nom du PC
        output_dir: Répertoire de sortie

    Returns:
        Path vers le fichier HTML généré
    """
    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        # Générer le nom du fichier
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"PlanetDiag_{machine_name}_{ts}_AI_ANALYSIS.html"
        html_path = output_dir / filename

        # Convertir markdown → HTML
        content_html = _markdown_to_html(mistral_analysis)

        # Générer le HTML complet
        html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PlanetDiag - Analyse Mistral IA</title>
    <style>
        {_get_css()}
    </style>
</head>
<body>
    <header>
        <h1>🤖 Analyse Mistral IA - PlanetDiag</h1>
        <div class="meta">
            <p><strong>Machine:</strong> {html.escape(machine_name)}</p>
            <p><strong>Généré:</strong> <span class="timestamp">{datetime.now().strftime("%d/%m/%Y à %H:%M:%S")}</span></p>
            <p><strong>Modèle:</strong> Mistral Large (analyse experte)</p>
        </div>
    </header>

    <main>
        <div class="section">
            {content_html}
        </div>
    </main>

    <footer>
        <p>Rapport généré par <strong>PlanetDiag</strong> v1.2.1</p>
        <p>Analyse effectuée par Mistral IA — à recouper avec le rapport technique complet</p>
    </footer>
</body>
</html>"""

        # Sauvegarder le fichier
        html_path.write_text(html_content, encoding="utf-8")
        logger.info(f"Rapport Mistral généré: {html_path}")

        return html_path

    except Exception as e:
        logger.exception(f"Erreur génération rapport Mistral: {e}")
        raise RuntimeError(f"Erreur génération rapport: {e}")
