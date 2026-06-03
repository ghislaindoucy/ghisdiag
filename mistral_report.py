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


def _markdown_to_html(markdown_text: str) -> str:
    """
    Convertit le texte markdown en HTML de manière basique.
    (pas de dépendance externe requise)
    """
    html_text = html.escape(markdown_text)

    # Titres H1-H6
    html_text = re.sub(r'^### (.*?)$', r'<h3>\1</h3>', html_text, flags=re.MULTILINE)
    html_text = re.sub(r'^## (.*?)$', r'<h2>\1</h2>', html_text, flags=re.MULTILINE)
    html_text = re.sub(r'^# (.*?)$', r'<h1>\1</h1>', html_text, flags=re.MULTILINE)

    # Listes
    html_text = re.sub(r'^\* (.*?)$', r'<li>\1</li>', html_text, flags=re.MULTILINE)
    html_text = re.sub(r'^- (.*?)$', r'<li>\1</li>', html_text, flags=re.MULTILINE)
    html_text = re.sub(r'^(\d+)\. (.*?)$', r'<li>\2</li>', html_text, flags=re.MULTILINE)

    # Wrapper les listes
    html_text = re.sub(r'(<li>.*?</li>)', lambda m: m.group(1).replace('<li>', '').replace('</li>', ''),
                       html_text, flags=re.DOTALL)
    html_text = re.sub(r'((?:<li>.*?</li>\n?)+)', r'<ul>\1</ul>', html_text, flags=re.MULTILINE)

    # Code inline et blocks
    html_text = re.sub(r'`([^`]+)`', r'<code>\1</code>', html_text)
    html_text = re.sub(r'```(.*?)```', r'<pre><code>\1</code></pre>', html_text, flags=re.DOTALL)

    # Gras et italique
    html_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html_text)
    html_text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', html_text)
    html_text = re.sub(r'__(.*?)__', r'<strong>\1</strong>', html_text)
    html_text = re.sub(r'_(.*?)_', r'<em>\1</em>', html_text)

    # Paragraphes
    lines = html_text.split('\n')
    formatted_lines = []
    in_block = False

    for line in lines:
        if line.startswith('<h') or line.startswith('<ul') or line.startswith('<pre') or \
           line.startswith('<table'):
            formatted_lines.append(line)
            in_block = True
        elif line.strip() == '':
            formatted_lines.append('</p>' if in_block and not line.startswith('<') else '')
            in_block = False
        elif not line.startswith('<'):
            if not in_block:
                formatted_lines.append('<p>')
                in_block = True
            formatted_lines.append(line)
        else:
            formatted_lines.append(line)

    html_text = '\n'.join(formatted_lines)

    # Remplacer les balises structurelles
    html_text = html_text.replace('<li>', '<li>')
    html_text = html_text.replace('</li>', '</li>')

    return html_text


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

    .status {{
        display: inline-block;
        padding: 0.5rem 1rem;
        border-radius: 4px;
        font-weight: 600;
        margin: 0.5rem 0;
    }}

    .status.ok {{
        background-color: rgba({GREEN}, 0.2);
        color: {GREEN};
        border: 1px solid {GREEN};
    }}

    .status.warning {{
        background-color: rgba({YELLOW}, 0.2);
        color: {YELLOW};
        border: 1px solid {YELLOW};
    }}

    .status.critical {{
        background-color: rgba({RED}, 0.2);
        color: {RED};
        border: 1px solid {RED};
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
        <p>Analyse effectuée par Mistral IA | <a href="#">Voir le rapport technique complet</a></p>
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
