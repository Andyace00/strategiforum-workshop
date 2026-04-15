"""
Bygger workshop_strategiforum_standalone.html — en selvstendig fil som kan
deles med andre uten server. Embedder alle bilder som base64 data-URIs.

ADVARSEL: Standalone-versjonen kan IKKE koble til WebSocket fra file://, så
AI-destillering og live bord-svar vil ikke fungere der. Den er ment for:
  - Forhåndsvisning / delbar demo
  - Sende til Øyvind/Therese for kommentar
  - PDF-eksport

For live workshop: bruk Render-URL-en.
"""
import base64
import pathlib
import re

BASE = pathlib.Path(__file__).parent
SRC = BASE / "workshop_strategiforum.html"
OUT = BASE / "workshop_strategiforum_standalone.html"

html = SRC.read_text(encoding="utf-8")

# Finn alle url('images/...') referanser og embed dem
image_refs = set(re.findall(r"url\('(images/[^']+)'\)", html))
print(f"Finner {len(image_refs)} unike bilde-referanser:")

for ref in image_refs:
    img_path = BASE / ref
    if not img_path.exists():
        print(f"  MANGLER: {ref}")
        continue
    data = img_path.read_bytes()
    ext = img_path.suffix.lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}.get(ext, "jpeg")
    b64 = base64.b64encode(data).decode("ascii")
    data_uri = f"data:image/{mime};base64,{b64}"
    html = html.replace(f"url('{ref}')", f"url('{data_uri}')")
    print(f"  OK {ref} ({len(data)//1024} kB → base64)")

# Standalone-modus: merk i title + fjern live-avhengigheter elegant
html = html.replace(
    "<title>Strategiforum — Møteplasser i Nordre Follo · 30.04.2026</title>",
    "<title>Strategiforum — Standalone forhåndsvisning (ikke live)</title>",
)

# Legg til en standalone-banner øverst
banner_css = """
.standalone-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  background: rgba(228, 188, 92, 0.95);
  color: #001B35;
  padding: 6px 16px;
  font-size: 11px;
  font-weight: 700;
  text-align: center;
  z-index: 9999;
  font-family: "Public Sans", sans-serif;
  letter-spacing: 0.05em;
}
.deck { margin-top: 24px; }
"""
banner_html = '<div class="standalone-banner">STANDALONE FORHÅNDSVISNING · ingen live-kobling · bruk Render-URL for workshop</div>'

html = html.replace("</style>\n</head>", banner_css + "\n</style>\n</head>")
html = html.replace('<body>\n\n<div class="nav-progress"', f'<body>\n\n{banner_html}\n<div class="nav-progress"')

OUT.write_text(html, encoding="utf-8")
print(f"\nStandalone: {OUT.name} ({len(html)//1024} kB)")
print("Kan deles direkte som fil (f.eks. e-post).")
