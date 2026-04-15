"""
Bildegenerator — Imagen 4.0 via Gemini API
==========================================
Genererer AI-bilder for de slotsene vi mangler ekte bilder til:

  1. images/lillestrom_bibliotek.jpg — fotorealistisk ref til moderne norsk
     kommunalt bibliotek, Lillestrøm-stil (samlokalisert med kulturskole,
     togstasjon, glassfasade). IKKE en logo, IKKE abstrakt.
  2. images/langhus_hypotese.jpg — illustrert visjon av hypotetisk
     hovedadresse på Langhus i 2035, i norsk småbykontekst.
  3. images/moteplass_hero.jpg — sterkere hero-bilde til slide 1,
     fotorealistisk, flere generasjoner møtes.

Ekte bilder brukes alltid der de finnes. Imagen fyller bare hull.

Krev:  GEMINI_API_KEY må være satt.
       pip install google-genai pillow

Kjør:  python generer_bilder.py
       python generer_bilder.py lillestrom   # bare én
"""
import os
import sys
from pathlib import Path

BASE = Path(__file__).parent
IMG_DIR = BASE / "images"
IMG_DIR.mkdir(exist_ok=True)

# Imagen 4.0 modell — krever aktiv Gemini API-nøkkel
IMAGEN_MODEL = os.environ.get("IMAGEN_MODEL", "imagen-4.0-generate-001")

# Prompter — "så ekte som mulig", fotorealistiske referanser
PROMPTS = {
    "lillestrom_bibliotek": {
        "file": "images/lillestrom_bibliotek.jpg",
        "prompt": (
            "A photorealistic editorial photograph of a modern Norwegian public "
            "library interior, similar in style to Lillestrøm bibliotek (opened 2022). "
            "Open-plan bibliotek and cultural school sharing the same building near a "
            "railway station. Warm natural light from floor-to-ceiling windows, "
            "Scandinavian wood detailing, children and elderly people reading and "
            "interacting, practical and well-used, NOT stylized or futuristic. "
            "Daytime, documentary style, editorial news photo quality. "
            "Aspect ratio 16:9, high resolution."
        ),
        "aspect": "16:9",
    },
    "langhus_hypotese": {
        "file": "images/langhus_hypotese.jpg",
        "prompt": (
            "A photorealistic editorial photograph of a hypothetical future "
            "community meeting place in a small Norwegian town (Langhus, Nordre Follo). "
            "A modest two-story brick-and-glass building by a pedestrian square in "
            "winter daylight, typical Norwegian small-town context. "
            "People of different ages coming and going — a teenager with a backpack, "
            "elderly couple, parent with stroller. Documentary style, restrained, "
            "not idealized. Aspect ratio 16:9."
        ),
        "aspect": "16:9",
    },
    "moteplass_hero": {
        "file": "images/moteplass_hero.jpg",
        "prompt": (
            "A photorealistic wide editorial photograph of an intergenerational "
            "community meeting place in Norway — a bright interior with library "
            "shelves, a small café, and people of all ages using the space together: "
            "children at a table, teenagers on a couch, an elderly woman with a "
            "friend, a father with a toddler. Natural light, warm wood, muted "
            "Scandinavian palette. Documentary news style, NOT stock photo, "
            "NOT rendered 3D. Aspect ratio 21:9 wide."
        ),
        "aspect": "16:9",
    },
}


def generate_image(key: str, spec: dict) -> bool:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print(f"[{key}] GEMINI_API_KEY ikke satt — hopper over.")
        return False

    try:
        from google import genai
    except ImportError:
        print("[error] Installer google-genai:  pip install google-genai")
        return False

    client = genai.Client(api_key=api_key)
    out_path = BASE / spec["file"]
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists():
        print(f"[{key}] finnes allerede: {out_path.name} (slett for å regenerere)")
        return True

    print(f"[{key}] genererer med {IMAGEN_MODEL}...")
    try:
        resp = client.models.generate_images(
            model=IMAGEN_MODEL,
            prompt=spec["prompt"],
            config={
                "number_of_images": 1,
                "aspect_ratio": spec.get("aspect", "16:9"),
                "person_generation": "allow_adult",
            },
        )
        if not resp.generated_images:
            print(f"[{key}] ingen bilder returnert")
            return False
        img = resp.generated_images[0].image
        img.save(str(out_path))
        print(f"[{key}] lagret: {out_path}")
        return True
    except Exception as e:
        print(f"[{key}] feilet: {e}")
        return False


def main():
    keys = sys.argv[1:] or list(PROMPTS.keys())
    ok = 0
    for key in keys:
        if key not in PROMPTS:
            print(f"[skip] ukjent: {key}")
            continue
        if generate_image(key, PROMPTS[key]):
            ok += 1
    print(f"\n{ok}/{len(keys)} genert.")
    print("\nNESTE STEG:")
    print("  1. Sjekk bildene i images/ visuelt før du bruker dem")
    print("  2. Hvis bildet ikke er bra nok: slett det og kjør scriptet igjen")
    print("  3. For Lillestrøm: helst erstatt med VERIFISERT pressefoto fra")
    print("     lillestrombibliotekene.no eller LPO Arkitekter før 30/4")


if __name__ == "__main__":
    main()
