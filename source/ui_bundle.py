"""Assemble the single self-contained document that the desktop window loads.

The interface is edited as ui/index.html, ui/studio.css and ui/studio.js. WebView2
receives one HTML string with the stylesheet and script inlined, so the page makes
no file or network requests and its Content-Security-Policy stays unchanged.
"""

from pathlib import Path
import re

ASSETS = [
    (re.compile(r'<link rel="stylesheet" href="studio\.css"\s*/?>'), 'studio.css', 'style'),
    (re.compile(r'<script src="studio\.js"></script>'), 'studio.js', 'script'),
]


def load(folder):
    folder = Path(folder)
    html = (folder / 'index.html').read_text(encoding='utf8')
    for pattern, name, tag in ASSETS:
        if len(pattern.findall(html)) != 1:
            raise RuntimeError(f'ui/index.html must reference {name} exactly once')
        content = (folder / name).read_text(encoding='utf8')
        if f'</{tag}' in content.lower():
            raise RuntimeError(f'{name} must not contain a closing {tag} tag')
        html = pattern.sub(lambda match, content=content, tag=tag: f'<{tag}>\n{content}</{tag}>', html)
    return html
