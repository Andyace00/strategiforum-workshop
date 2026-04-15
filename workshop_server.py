"""
Strategiforum Workshop Server v3 — Møteplasser i Nordre Follo
================================================================
FastAPI + WebSocket. AI er synlig for hele rommet: alle Gemini-utkast
broadcastes og vises i presentasjonen, ingen skjult fasilitator-panel.

Runder:
  r1_bilde2035       - freetext
  r2_prinsipper      - freetext  → AI destillerer (med r1 som kontekst)
  r3_hovedadresser   - categorized (Ski / Kolbotn / Langhus)
  r4_langhus         - rating 1-5
  r5_satellitter     - categorized (Kan flyttes / Må vurderes / Urørlig)
  r6_dilemma         - freetext  → AI kobler dilemma til prinsipper
  r7_konsensus       - rating 1-5

AI-ekstra:
  /api/destill-prinsipper  → r2-destillering, med r1+kartlegging som kontekst
  /api/koble-dilemma       → r6-dilemma koblet til r2-prinsipper
  /api/kd-utkast           → utkast til kommunedirektørens slide-21-setning
  /api/sluttsyntese        → én setning som binder hele workshopen

Kjør:  python workshop_server.py
       http://localhost:8000/admin    fasilitator
       http://localhost:8000/p        bord-sekretær
       http://localhost:8000/wall     live-vegg (valgfritt)
"""
import os
import json
import socket
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ====================================================================
# GEMINI
# ====================================================================
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
gemini_client = None
if GEMINI_KEY:
    try:
        from google import genai
        gemini_client = genai.Client(api_key=GEMINI_KEY)
        print(f"[Gemini] aktiv · modell {GEMINI_MODEL}")
    except Exception as e:
        print(f"[Gemini] ikke tilgjengelig: {e}")
else:
    print("[Gemini] ingen GEMINI_API_KEY — fallbacks brukes")


def call_gemini_json(prompt: str, temperature: float = 0.4) -> Optional[dict]:
    """Kaller Gemini og returnerer parset JSON-objekt eller None."""
    if not gemini_client:
        return None
    try:
        from google.genai import types
        resp = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json",
            ),
        )
        text = (resp.text or "").strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text)
    except Exception as e:
        print(f"[Gemini] kall feilet: {e}")
        return None


# ====================================================================
# PATHS + CONTEXT
# ====================================================================
BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "workshop_data.json"
CONTEXT_FILE = BASE_DIR / "workshop_context.json"


def load_context() -> dict:
    if CONTEXT_FILE.exists():
        try:
            with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[context] lese-feil: {e}")
    return {}


WORKSHOP_CONTEXT = load_context()


# ====================================================================
# FASTAPI
# ====================================================================
app = FastAPI(title="Strategiforum Workshop Server v3")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ====================================================================
# STATE MODEL
# ====================================================================
DEFAULT_ROUNDS: Dict[str, dict] = {
    "r1_bilde2035": {
        "title": "Bildet av 2035",
        "question": "Når du ser for deg en levende møteplass i Nordre Follo i 2035 — hva er det første du ser?",
        "type": "freetext",
        "items": [],
        "active": False,
    },
    "r2_prinsipper": {
        "title": "Hva kjennetegner en hovedadresse?",
        "question": "Hva kjennetegner en hovedadresse — ikke bare et bygg? Én setning fra gruppen.",
        "type": "freetext",
        "items": [],
        "destilled": [],
        "active": False,
    },
    "r3_hovedadresser": {
        "title": "Målgrupper og magneter per møteplass",
        "question": "For hver av de tre møteplassene — hvem er de for, og hva er magneten? Format: 'målgruppe — aktivitet'.",
        "type": "categorized",
        "categories": ["Ski", "Kolbotn", "Langhus"],
        "items": [],
        "active": False,
    },
    "r4_langhus": {
        "title": "Skal Langhus være nr 3?",
        "question": "Nå som dere har tegnet hva Langhus ville vært — skal det være kommunens tredje hovedadresse? 1=nei, 5=ja. Legg ved betingelser.",
        "type": "rating",
        "ratings": [],
        "active": False,
    },
    "r5_satellitter": {
        "title": "Satellittenes skjebne",
        "question": "Hvilke satellitter kan vi gi slipp på — og hvilke kan vi ikke? Sorter hvert bygg. Senior + kultur, skal også ivareta ungdom 15-20.",
        "type": "categorized",
        "categories": ["Kan flyttes", "Må vurderes", "Urørlig"],
        "pre_items": [
            "Toppenhaug seniorsenter (ca. 480 kvm · kafé/quiz/bingo/snekker/fotpleie)",
            "Svingen seniorsenter (ca. 655 kvm · kafé/sløyd/håndarbeid/trening/språkkurs)",
            "Kolben senior — leid av Samfunnshuset (ca. 520 kvm · festsal/trening)",
            "Kontra kulturskole (1 580 kvm egne + 350 leid · til 2031)",
            "K26 (ca. 170 kvm · kafé/kjøkken/utstilling)",
        ],
        "items": [],
        "active": False,
    },
    "r6_dilemma": {
        "title": "Dilemma-eierskap",
        "question": "Hvilket dilemma tar din gruppe personlig eierskap til å følge opp etter forumet?",
        "type": "freetext",
        "items": [],
        "active": False,
    },
    "r7_konsensus": {
        "title": "Samlet konsensus",
        "question": "Kan din gruppe stille seg bak retningen vi har landet på i dag? 1=nei, 3=kan leve med, 5=helt.",
        "type": "rating",
        "ratings": [],
        "active": False,
    },
}


def _default_state() -> dict:
    return {
        "session_started": datetime.now().isoformat(),
        "active_round": None,
        "participants": {},
        "rounds": json.loads(json.dumps(DEFAULT_ROUNDS)),
        "ai_cache": {
            "dilemma_kobling": None,
            "kd_utkast": None,
            "sluttsyntese": None,
        },
        "ai_meta": {},
    }


def load_state() -> dict:
    if not DATA_FILE.exists():
        return _default_state()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except Exception as e:
        print(f"[state] lesefeil: {e}")
        return _default_state()

    default_copy = json.loads(json.dumps(DEFAULT_ROUNDS))
    saved_rounds = saved.get("rounds", {})
    merged: Dict[str, dict] = {}
    for rid, default_r in default_copy.items():
        if rid in saved_rounds:
            merged_r = dict(default_r)
            for field in ("items", "ratings", "destilled", "active"):
                if field in saved_rounds[rid]:
                    merged_r[field] = saved_rounds[rid][field]
            merged[rid] = merged_r
        else:
            merged[rid] = default_r
    saved["rounds"] = merged
    saved.setdefault("session_started", datetime.now().isoformat())
    saved.setdefault("active_round", None)
    saved.setdefault("participants", {})
    saved.setdefault("ai_cache", {"dilemma_kobling": None, "kd_utkast": None, "sluttsyntese": None})
    saved.setdefault("ai_meta", {})
    return saved


def save_state():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(STATE, f, ensure_ascii=False, indent=2)


STATE = load_state()


# ====================================================================
# WEBSOCKET CONNECTIONS
# ====================================================================
class ConnectionManager:
    def __init__(self):
        self.connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.add(ws)

    def disconnect(self, ws: WebSocket):
        self.connections.discard(ws)

    async def broadcast(self, message: dict):
        dead = set()
        for ws in self.connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        self.connections -= dead


manager = ConnectionManager()


# ====================================================================
# HELPERS
# ====================================================================
def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def collect_round_items_text(round_id: str) -> List[str]:
    r = STATE["rounds"].get(round_id, {})
    return [(it.get("value") or "").strip() for it in r.get("items", []) if (it.get("value") or "").strip()]


def collect_categorized_items(round_id: str) -> Dict[str, List[str]]:
    r = STATE["rounds"].get(round_id, {})
    out: Dict[str, List[str]] = {c: [] for c in r.get("categories", [])}
    for it in r.get("items", []):
        cat = it.get("category")
        val = (it.get("value") or "").strip()
        if cat in out and val:
            out[cat].append(val)
    return out


def collect_ratings(round_id: str) -> dict:
    r = STATE["rounds"].get(round_id, {})
    rs = r.get("ratings", [])
    if not rs:
        return {"count": 0, "avg": None, "comments": []}
    vals = [rt.get("value", 0) for rt in rs]
    avg = sum(vals) / len(vals)
    comments = [rt.get("comment", "").strip() for rt in rs if rt.get("comment")]
    return {"count": len(vals), "avg": round(avg, 2), "comments": comments}


def format_context_block() -> str:
    """Formaterer workshop_context.json som tekst for prompts."""
    ctx = WORKSHOP_CONTEXT
    parts = []
    dom = ctx.get("domene", {})
    if dom:
        parts.append("DOMENE:")
        parts.append(f"  {dom.get('navn', '')}: {dom.get('definisjon', '')}")
        parts.append(f"  Narrativ: {dom.get('narrativ', '')}")
    ev = ctx.get("evidens", {})
    if ev:
        parts.append("EVIDENS:")
        parts.append(f"  Areal: {ev.get('areal_samlet_kvm', '?')} kvm samlet ({ev.get('areal_leid_kvm','?')} leid, {ev.get('areal_eid_kvm','?')} eid inkl. K26)")
        parts.append(f"  Innbyggere: {ev.get('innbyggere', '?')}")
    tone = ctx.get("tone_og_språk", {})
    if tone:
        parts.append("TONE: " + ", ".join(tone.get("skal_være", [])[:3]))
        parts.append("UNNGÅ: " + ", ".join(tone.get("skal_unngås", [])[:3]))
    return "\n".join(parts)


def format_kartlegging_block() -> str:
    """Nåsituasjon fra Eiendom/kartleggingene som kontekst for prompts."""
    return (
        "KARTLEGGING (Eiendom 2026):\n"
        "  Ski bibliotek: ca. 1 843 kvm (biblioteksal 1 296, lesesal 107, ungdomsavd 65, hist. arkiv 68)\n"
        "  Kolbotn bibliotek: ca. 1 426 kvm (biblioteksal 997, galleri 82, lesesal 44)\n"
        "  Kolben kulturhus: ca. 842 kvm egne rom\n"
        "  Kontra kulturskole: ca. 1 580 kvm egne + 350 kvm leid i Kolben (til 2031)\n"
        "  Toppenhaug seniorsenter: ca. 480 kvm (kafé/quiz/bingo man-fre, snekker, fotpleie)\n"
        "  Svingen seniorsenter: ca. 655 kvm (kafé, sløyd, håndarbeid, trening, språkkurs, kjøkken til hjemmeboende)\n"
        "  Kolben senior (leid): ca. 520 kvm (festsal, trening, quiz)\n"
        "  K26: ca. 170 kvm (kafé, kjøkken, utstilling)"
    )


# ====================================================================
# AI: r2_prinsipper — destillering (med r1 + kartlegging som kontekst)
# ====================================================================
def build_prinsipper_prompt() -> str:
    r1_items = collect_round_items_text("r1_bilde2035")
    r2_items = collect_round_items_text("r2_prinsipper")
    parts = [
        "# ROLLE",
        "Du destillerer prinsipper fra et strategiforum for direktører og kommunalsjefer i Nordre Follo kommune.",
        "Input er ca. 10 gruppesvar på 'Hva kjennetegner en hovedadresse?' + bildene de laget i runde 1.",
        "",
        format_context_block(),
        "",
        format_kartlegging_block(),
        "",
        "# OPPGAVE",
        "Destiller 3-4 korte, skarpe prinsipper fra gruppesvarene i runde 2. Hvert prinsipp er en setning på 8-16 ord.",
        "Bruk deltakernes egne ord der mulig. Ikke legg til prinsipper som ikke er støttet i minst én gruppes svar.",
        "Bruk bildene fra runde 1 for å forstå hvilken stemning prinsippene skal forankres i — men ikke sitér fra r1.",
        "",
        "# R1 — Bildene av 2035 (kontekst, ikke input)",
    ]
    if r1_items:
        for i, s in enumerate(r1_items, 1):
            parts.append(f"  {i}. {s}")
    else:
        parts.append("  (ingen svar enda)")
    parts += [
        "",
        "# R2 — Gruppesvar (skal destilleres)",
    ]
    if r2_items:
        for i, s in enumerate(r2_items, 1):
            parts.append(f"  {i}. {s}")
    else:
        parts.append("  (ingen svar enda)")
    parts += [
        "",
        "# OUTPUT (JSON)",
        'Returner KUN: {"items": ["prinsipp 1", "prinsipp 2", "prinsipp 3", "prinsipp 4"]}',
        'Ingen forklaring, ingen markdown.',
    ]
    return "\n".join(parts)


def fallback_destill_prinsipper(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for it in items:
        norm = " ".join((it or "").lower().split())
        if norm in seen or len(norm.split()) < 4:
            continue
        seen.add(norm)
        out.append(it)
        if len(out) >= 4:
            break
    return out


# ====================================================================
# AI: r6_dilemma — kobling til prinsipper
# ====================================================================
def build_dilemma_kobling_prompt() -> str:
    dilemmaer = collect_round_items_text("r6_dilemma")
    prinsipper = STATE["rounds"]["r2_prinsipper"].get("destilled", []) or []
    satellitter = collect_categorized_items("r5_satellitter")

    parts = [
        "# ROLLE",
        "Du kobler dilemmaene fra runde 6 til prinsippene fra runde 2 i samme strategiforum.",
        "",
        "# PRINSIPPER (fra r2)",
    ]
    if prinsipper:
        for i, p in enumerate(prinsipper, 1):
            parts.append(f"  {i}. {p}")
    else:
        parts.append("  (ingen destillerte prinsipper enda)")

    parts += ["", "# SATELLITT-SORTERING (fra r5)"]
    for cat, vals in satellitter.items():
        if vals:
            parts.append(f"  {cat}: " + "; ".join(vals[:6]))

    parts += ["", "# DILEMMAER (fra r6 — skal kobles)"]
    if dilemmaer:
        for i, d in enumerate(dilemmaer, 1):
            parts.append(f"  {i}. {d}")
    else:
        parts.append("  (ingen dilemmaer enda)")

    parts += [
        "",
        "# OPPGAVE",
        "For hvert dilemma: identifiser hvilket prinsipp fra r2 det er tettest koblet til, og skriv én setning som forklarer koblingen.",
        "Bruk deltakernes egne ord. Vær presis, ikke generell. Hvis et dilemma ikke matcher noe prinsipp — vær ærlig og si det.",
        "",
        "# OUTPUT (JSON)",
        'Returner: {"koblinger": [{"dilemma": "...", "prinsipp": "...", "kobling": "forklaring i én setning"}]}',
    ]
    return "\n".join(parts)


def fallback_dilemma_kobling() -> List[dict]:
    dilemmaer = collect_round_items_text("r6_dilemma")
    prinsipper = STATE["rounds"]["r2_prinsipper"].get("destilled", []) or []
    out = []
    for i, d in enumerate(dilemmaer):
        p = prinsipper[i % len(prinsipper)] if prinsipper else "—"
        out.append({
            "dilemma": d,
            "prinsipp": p,
            "kobling": f"Dilemmaet berører prinsippet direkte — manuell kobling kreves.",
        })
    return out


# ====================================================================
# AI: slide 21 — Kommunedirektørens setning (utkast)
# ====================================================================
def build_kd_utkast_prompt() -> str:
    prinsipper = STATE["rounds"]["r2_prinsipper"].get("destilled", []) or []
    r4 = collect_ratings("r4_langhus")
    r7 = collect_ratings("r7_konsensus")
    satellitter = collect_categorized_items("r5_satellitter")
    hovedadresser = collect_categorized_items("r3_hovedadresser")
    dilemmaer = collect_round_items_text("r6_dilemma")

    parts = [
        "# ROLLE",
        "Du skriver et utkast til kommunedirektør Øyvinds sluttsetning ('Retningen slik jeg leser den') i et strategiforum i Nordre Follo.",
        "Setningen skal være editorial, varm, konkret — ikke konsulent-norsk. Skal leses høyt foran direktører og kommunalsjefer.",
        "Øyvind justerer utkastet før han leser det opp.",
        "",
        format_context_block(),
        "",
        "# PRINSIPPER (r2)",
    ]
    if prinsipper:
        parts += [f"  - {p}" for p in prinsipper]
    else:
        parts.append("  (ingen)")

    parts += ["", "# HOVEDADRESSER — magneter (r3)"]
    for sted, vals in hovedadresser.items():
        if vals:
            parts.append(f"  {sted}: " + "; ".join(vals[:5]))

    parts += ["", f"# LANGHUS-RATING (r4): snitt {r4.get('avg','—')}/5 fra {r4.get('count',0)} grupper"]
    if r4.get("comments"):
        parts.append("  Betingelser:")
        for c in r4["comments"][:5]:
            parts.append(f"    - {c}")

    parts += ["", "# SATELLITT-SORTERING (r5)"]
    for cat, vals in satellitter.items():
        if vals:
            parts.append(f"  {cat}: " + "; ".join(vals[:6]))

    parts += ["", "# DILEMMAER (r6)"]
    if dilemmaer:
        for d in dilemmaer[:8]:
            parts.append(f"  - {d}")

    parts += ["", f"# KONSENSUS (r7): snitt {r7.get('avg','—')}/5 fra {r7.get('count',0)} grupper"]

    parts += [
        "",
        "# OPPGAVE",
        "Skriv ÉN sammenhengende editorial setning (maks 60 ord) som Øyvind kan lese opp.",
        "Struktur: 1) hvor vi står i 2035, 2) hva vi bygger rundt, 3) hva vi gir slipp på, 4) hva vi styrker som forebygging.",
        "Bruk deltakernes egne ord fra prinsippene. Aldri: 'synergi', 'verdiskaping', 'co-creation', 'både-og' uten kant.",
        "Beholde formuleringen 'som ikke bærer sin egen vekt' (Thereses ønske).",
        "Inkludér forebygging av både eldre og ungdom (ikke bare sykehjemsbehov).",
        "",
        "# OUTPUT (JSON)",
        'Returner: {"setning": "..."}',
    ]
    return "\n".join(parts)


FALLBACK_KD_SETNING = (
    "Nordre Follos møteplasser i 2035 er samlet på få, sterke adresser. "
    "Vi bygger dagen rundt mennesker og aktiviteter, ikke rundt bygg. "
    "Og vi gir slipp på det som ikke bærer sin egen vekt — samtidig som vi styrker "
    "det forebyggende: både det som utsetter sykehjemsbehovet og det som gir "
    "ungdom et sted å høre til."
)


# ====================================================================
# AI: slide 22 — Sluttsyntese
# ====================================================================
def build_sluttsyntese_prompt() -> str:
    prinsipper = STATE["rounds"]["r2_prinsipper"].get("destilled", []) or []
    r4 = collect_ratings("r4_langhus")
    r7 = collect_ratings("r7_konsensus")
    dilemmaer = collect_round_items_text("r6_dilemma")
    satellitter = collect_categorized_items("r5_satellitter")

    parts = [
        "# ROLLE",
        "Du skriver ÉN sluttsyntese-setning som oppsummerer hele strategiforumet i Nordre Follo.",
        "Denne vises på sluttsliden foran hele rommet. Maks 40 ord.",
        "",
        format_context_block(),
        "",
        "# PRINSIPPER (r2)",
    ]
    if prinsipper:
        parts += [f"  - {p}" for p in prinsipper]

    parts += [
        "", f"# LANGHUS (r4): snitt {r4.get('avg','—')}/5",
        f"# KONSENSUS (r7): snitt {r7.get('avg','—')}/5",
        "", "# DILEMMAER som tas videre",
    ]
    for d in dilemmaer[:5]:
        parts.append(f"  - {d}")

    parts += [
        "", "# SATELLITTER",
    ]
    for cat, vals in satellitter.items():
        if vals:
            parts.append(f"  {cat}: {len(vals)} bygg")

    parts += [
        "",
        "# OPPGAVE",
        "Én setning, maks 40 ord, som binder dagens retning sammen. Editorial, varm, konkret. Ikke konsulent-norsk.",
        "",
        "# OUTPUT (JSON)",
        'Returner: {"setning": "..."}',
    ]
    return "\n".join(parts)


FALLBACK_SLUTTSYNTESE = (
    "Vi har ikke landet det ferdig — vi har landet retningen: samle liv på få adresser, "
    "gi slipp på det som ikke bærer sin egen vekt, og styrke det forebyggende for alle aldre."
)


# ====================================================================
# ROUTES — BASIS
# ====================================================================
@app.get("/")
async def root():
    return HTMLResponse(LANDING_HTML.replace("{{IP}}", get_local_ip()))


@app.get("/admin", response_class=HTMLResponse)
async def admin():
    return HTMLResponse(ADMIN_HTML)


@app.get("/show", response_class=HTMLResponse)
async def show_presentation():
    """Serverer presentasjonen fra samme origin som WebSocket."""
    f = BASE_DIR / "workshop_strategiforum.html"
    if not f.exists():
        return HTMLResponse("<h1>workshop_strategiforum.html ikke funnet</h1>", status_code=404)
    return FileResponse(str(f), media_type="text/html; charset=utf-8")


@app.get("/nf_kart.html", response_class=HTMLResponse)
async def nf_kart():
    f = BASE_DIR / "nf_kart.html"
    if not f.exists():
        return HTMLResponse("<h1>nf_kart.html ikke funnet</h1>", status_code=404)
    return FileResponse(str(f), media_type="text/html; charset=utf-8")


@app.get("/images/{filepath:path}")
async def serve_image(filepath: str):
    """Serverer bilder fra images/-mappa. Sikker path-validering."""
    # Enkel path traversal-beskyttelse
    if ".." in filepath or filepath.startswith("/"):
        return JSONResponse({"error": "invalid path"}, status_code=400)
    f = BASE_DIR / "images" / filepath
    if not f.exists() or not f.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(f))


@app.get("/healthz")
async def healthz():
    """Health check for Render + keepalive-cron."""
    return {"status": "ok", "active_round": STATE.get("active_round"), "ai_ready": gemini_client is not None}


@app.get("/p", response_class=HTMLResponse)
async def participant():
    return HTMLResponse(PARTICIPANT_HTML)


@app.get("/wall", response_class=HTMLResponse)
async def wall():
    return HTMLResponse(WALL_HTML)


@app.get("/api/state")
async def get_state():
    return JSONResponse(STATE)


@app.get("/api/context")
async def get_context():
    return JSONResponse(WORKSHOP_CONTEXT)


@app.get("/api/export")
async def export():
    return JSONResponse(STATE, headers={"Content-Disposition": "attachment; filename=workshop_export.json"})


@app.post("/api/round/{round_id}/activate")
async def activate_round(round_id: str):
    if round_id not in STATE["rounds"]:
        return JSONResponse({"error": "ukjent runde"}, status_code=404)
    for r in STATE["rounds"].values():
        r["active"] = False
    STATE["rounds"][round_id]["active"] = True
    STATE["active_round"] = round_id
    save_state()
    await manager.broadcast({"type": "round_changed", "round_id": round_id, "state": STATE})
    return {"ok": True}


@app.post("/api/round/{round_id}/clear")
async def clear_round(round_id: str):
    if round_id not in STATE["rounds"]:
        return JSONResponse({"error": "ukjent runde"}, status_code=404)
    r = STATE["rounds"][round_id]
    if "items" in r:
        r["items"] = []
    if "ratings" in r:
        r["ratings"] = []
    if "destilled" in r:
        r["destilled"] = []
    save_state()
    await manager.broadcast({"type": "round_cleared", "round_id": round_id, "state": STATE})
    return {"ok": True}


# ====================================================================
# ROUTES — AI
# ====================================================================
def _ts() -> str:
    return datetime.now().isoformat()


@app.post("/api/destill-prinsipper")
async def api_destill_prinsipper():
    items = collect_round_items_text("r2_prinsipper")
    if not items:
        return JSONResponse({"error": "ingen svar enda", "items": []})
    prompt = build_prinsipper_prompt()
    parsed = call_gemini_json(prompt, temperature=0.4)
    principles: List[str] = []
    ai_used = False
    if parsed and isinstance(parsed.get("items"), list):
        principles = [str(p).strip() for p in parsed["items"] if str(p).strip()][:4]
        ai_used = bool(principles)
    if not principles:
        principles = fallback_destill_prinsipper(items)
    STATE["rounds"]["r2_prinsipper"]["destilled"] = principles
    STATE.setdefault("ai_meta", {})["r2"] = {"ai_used": ai_used, "model": GEMINI_MODEL if ai_used else "fallback", "ts": _ts()}
    save_state()
    result = {"items": principles, "meta": STATE["ai_meta"]["r2"]}
    await manager.broadcast({"type": "ai_result", "target": "r2", "result": result, "meta": STATE["ai_meta"]["r2"], "state": STATE})
    return result


@app.post("/api/koble-dilemma")
async def api_koble_dilemma():
    dilemmaer = collect_round_items_text("r6_dilemma")
    if not dilemmaer:
        return JSONResponse({"error": "ingen dilemmaer enda", "koblinger": []})
    prompt = build_dilemma_kobling_prompt()
    parsed = call_gemini_json(prompt, temperature=0.45)
    koblinger: List[dict] = []
    ai_used = False
    if parsed and isinstance(parsed.get("koblinger"), list):
        koblinger = parsed["koblinger"]
        ai_used = bool(koblinger)
    if not koblinger:
        koblinger = fallback_dilemma_kobling()
    STATE.setdefault("ai_cache", {})["dilemma_kobling"] = {"koblinger": koblinger}
    STATE.setdefault("ai_meta", {})["r6"] = {"ai_used": ai_used, "model": GEMINI_MODEL if ai_used else "fallback", "ts": _ts()}
    save_state()
    result = {"koblinger": koblinger, "meta": STATE["ai_meta"]["r6"]}
    await manager.broadcast({"type": "ai_result", "target": "r6", "result": result, "meta": STATE["ai_meta"]["r6"], "state": STATE})
    return result


@app.post("/api/kd-utkast")
async def api_kd_utkast():
    prompt = build_kd_utkast_prompt()
    parsed = call_gemini_json(prompt, temperature=0.55)
    setning = ""
    ai_used = False
    if parsed and isinstance(parsed.get("setning"), str):
        setning = parsed["setning"].strip()
        ai_used = bool(setning)
    if not setning:
        setning = FALLBACK_KD_SETNING
    STATE.setdefault("ai_cache", {})["kd_utkast"] = {"setning": setning}
    STATE.setdefault("ai_meta", {})["r21"] = {"ai_used": ai_used, "model": GEMINI_MODEL if ai_used else "fallback", "ts": _ts()}
    save_state()
    result = {"setning": setning, "meta": STATE["ai_meta"]["r21"]}
    await manager.broadcast({"type": "ai_result", "target": "r21", "result": result, "meta": STATE["ai_meta"]["r21"], "state": STATE})
    return result


@app.post("/api/sluttsyntese")
async def api_sluttsyntese():
    prompt = build_sluttsyntese_prompt()
    parsed = call_gemini_json(prompt, temperature=0.5)
    setning = ""
    ai_used = False
    if parsed and isinstance(parsed.get("setning"), str):
        setning = parsed["setning"].strip()
        ai_used = bool(setning)
    if not setning:
        setning = FALLBACK_SLUTTSYNTESE
    STATE.setdefault("ai_cache", {})["sluttsyntese"] = {"setning": setning}
    STATE.setdefault("ai_meta", {})["r22"] = {"ai_used": ai_used, "model": GEMINI_MODEL if ai_used else "fallback", "ts": _ts()}
    save_state()
    result = {"setning": setning, "meta": STATE["ai_meta"]["r22"]}
    await manager.broadcast({"type": "ai_result", "target": "r22", "result": result, "meta": STATE["ai_meta"]["r22"], "state": STATE})
    return result


# ====================================================================
# WEBSOCKET
# ====================================================================
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        await ws.send_json({"type": "welcome", "state": STATE})
        while True:
            data = await ws.receive_json()
            await handle_ws_message(data, ws)
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as e:
        print(f"[ws] feil: {e}")
        manager.disconnect(ws)


async def handle_ws_message(data: dict, ws: WebSocket):
    t = data.get("type")

    if t == "register":
        user_id = data.get("user_id") or "anon"
        user_name = data.get("user_name") or "Anonym"
        STATE["participants"][user_id] = user_name
        save_state()
        await manager.broadcast({"type": "participant_joined", "user_id": user_id, "state": STATE})
        return

    if t == "submit_freetext":
        round_id = data.get("round_id")
        user_id = data.get("user_id") or "anon"
        value = (data.get("value") or "").strip()
        if not value or round_id not in STATE["rounds"]:
            return
        r = STATE["rounds"][round_id]
        if r.get("type") != "freetext":
            return
        r["items"] = [it for it in r.get("items", []) if it.get("user_id") != user_id]
        r["items"].append({"user_id": user_id, "value": value, "ts": _ts()})
        save_state()
        await manager.broadcast({"type": "freetext_added", "round_id": round_id, "state": STATE})
        return

    if t == "submit_rating":
        round_id = data.get("round_id")
        user_id = data.get("user_id") or "anon"
        value = data.get("value")
        comment = (data.get("comment") or "").strip()
        if round_id not in STATE["rounds"]:
            return
        r = STATE["rounds"][round_id]
        if r.get("type") != "rating":
            return
        try:
            v = int(value)
            if v < 1 or v > 5:
                return
        except Exception:
            return
        r["ratings"] = [rt for rt in r.get("ratings", []) if rt.get("user_id") != user_id]
        r["ratings"].append({"user_id": user_id, "value": v, "comment": comment, "ts": _ts()})
        save_state()
        await manager.broadcast({"type": "rating_added", "round_id": round_id, "state": STATE})
        return

    if t == "submit_categorized":
        round_id = data.get("round_id")
        user_id = data.get("user_id") or "anon"
        value = (data.get("value") or "").strip()
        category = data.get("category")
        if not value or round_id not in STATE["rounds"]:
            return
        r = STATE["rounds"][round_id]
        if r.get("type") != "categorized":
            return
        if category not in r.get("categories", []):
            return
        r.setdefault("items", []).append({
            "user_id": user_id, "value": value, "category": category, "ts": _ts(),
        })
        save_state()
        await manager.broadcast({"type": "categorized_added", "round_id": round_id, "state": STATE})
        return

    if t == "delete_item":
        round_id = data.get("round_id")
        item_ts = data.get("ts")
        if round_id not in STATE["rounds"]:
            return
        r = STATE["rounds"][round_id]
        before = len(r.get("items", []))
        r["items"] = [it for it in r.get("items", []) if it.get("ts") != item_ts]
        if len(r["items"]) < before:
            save_state()
            await manager.broadcast({"type": "item_removed", "round_id": round_id, "state": STATE})


# ====================================================================
# HTML TEMPLATES — NFK Mørk-stilt
# ====================================================================
_NFK_CSS = """
body { font-family: "Public Sans", -apple-system, "Segoe UI", sans-serif; background: #001B35; color: #E8F0F5; margin: 0; padding: 32px; }
h1 { color: #4FB3B6; margin: 0 0 6px; font-size: 28px; font-weight: 700; }
.sub { color: #A8BECE; margin-bottom: 24px; font-size: 13px; }
.runde { background: rgba(0, 48, 87, 0.72); border: 1px solid rgba(79, 179, 182, 0.22); border-radius: 12px; padding: 16px 20px; margin-bottom: 12px; }
.runde.active { border-color: #5BB67E; background: rgba(91, 182, 126, 0.08); }
.runde-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.runde-id { font-family: ui-monospace, monospace; color: #6ED1D4; font-size: 11px; }
.runde-title { font-size: 17px; font-weight: 700; color: #ffffff; }
.runde-q { font-size: 12px; color: #A8BECE; margin: 6px 0 10px; }
.runde-count { font-size: 11px; color: #A8BECE; }
.btns { display: flex; gap: 6px; }
.btn { background: rgba(0, 48, 87, 0.72); border: 1px solid rgba(79, 179, 182, 0.22); color: #A8BECE; padding: 6px 12px; border-radius: 6px; font-size: 12px; cursor: pointer; font-family: inherit; }
.btn:hover { background: rgba(79, 179, 182, 0.12); }
.btn.primary { background: #4FB3B6; color: #001B35; border-color: #4FB3B6; font-weight: 700; }
.btn.danger { color: #E07B7B; }
.banner { background: rgba(0, 48, 87, 0.72); padding: 12px 20px; border-radius: 8px; border: 1px solid rgba(79, 179, 182, 0.22); margin-bottom: 18px; font-size: 13px; color: #A8BECE; }
.banner strong { color: #6ED1D4; }
"""

LANDING_HTML = """<!DOCTYPE html>
<html lang="nb"><head><meta charset="UTF-8">
<title>Strategiforum Workshop Server v3</title>
<link href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700&display=swap" rel="stylesheet">
<style>
body { font-family: "Public Sans", -apple-system, "Segoe UI", sans-serif; background: #001B35; color: #E8F0F5; margin: 0; padding: 60px 40px; text-align: center; }
h1 { font-size: 36px; color: #4FB3B6; margin-bottom: 6px; font-weight: 800; }
.sub { color: #A8BECE; font-size: 17px; margin-bottom: 40px; }
.ip { display: inline-block; background: rgba(0, 48, 87, 0.72); border: 1px solid rgba(79, 179, 182, 0.22); padding: 18px 32px; border-radius: 10px; font-family: ui-monospace, monospace; font-size: 18px; margin-bottom: 40px; }
.ip strong { color: #6ED1D4; }
.cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; max-width: 900px; margin: 0 auto; }
.card { background: rgba(0, 48, 87, 0.72); border: 1px solid rgba(79, 179, 182, 0.22); border-radius: 12px; padding: 24px; text-decoration: none; color: #E8F0F5; transition: transform .15s, border-color .15s; }
.card:hover { transform: translateY(-3px); border-color: #4FB3B6; }
.card h2 { color: #6ED1D4; font-size: 18px; margin: 0 0 8px; }
.card p { color: #A8BECE; font-size: 13px; margin: 0; }
</style></head>
<body>
<h1>Strategiforum Workshop Server v3</h1>
<div class="sub">Møteplasser i Nordre Follo · 30. april 2026</div>
<div class="ip">Server: <strong>http://{{IP}}:8000</strong></div>
<div class="cards">
  <a class="card" href="/show"><h2>Presentasjon →</h2><p>22 slides · NFK Mørk · storskjerm</p></a>
  <a class="card" href="/admin"><h2>Admin →</h2><p>Aktiver runder, trigg AI</p></a>
  <a class="card" href="/p"><h2>Sekretær →</h2><p>Bord-input (en per laptop)</p></a>
</div>
</body></html>"""


ADMIN_HTML = """<!DOCTYPE html>
<html lang="nb"><head><meta charset="UTF-8">
<title>Admin — Strategiforum v3</title>
<link href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>""" + _NFK_CSS + """</style></head>
<body>
<h1>Admin — Strategiforum v3</h1>
<div class="sub">Møteplasser i Nordre Follo · 30. april 2026 · 7 runder</div>
<div class="banner" id="banner">Kobler til server...</div>
<div id="rounds"></div>
<div style="margin-top: 20px; display: flex; gap: 10px; flex-wrap: wrap;">
  <a class="btn" href="/api/export" download>Last ned eksport</a>
  <button class="btn" onclick="refresh()">Oppdater</button>
  <button class="btn primary" onclick="triggerAI('/api/destill-prinsipper', 'Destiller r2')">Destiller r2</button>
  <button class="btn primary" onclick="triggerAI('/api/koble-dilemma', 'Koble r6')">Koble r6</button>
  <button class="btn primary" onclick="triggerAI('/api/kd-utkast', 'Utkast r21')">Utkast r21</button>
  <button class="btn primary" onclick="triggerAI('/api/sluttsyntese', 'Syntese r22')">Syntese r22</button>
</div>
<script>
async function refresh() {
  const r = await fetch('/api/state');
  const s = await r.json();
  renderRounds(s);
}
function renderRounds(s) {
  const banner = document.getElementById('banner');
  banner.innerHTML = `<strong>${Object.keys(s.rounds).length}</strong> runder · aktiv: <strong>${s.active_round || 'ingen'}</strong> · ${Object.keys(s.participants).length} deltakere`;
  const div = document.getElementById('rounds');
  div.innerHTML = '';
  for (const [id, r] of Object.entries(s.rounds)) {
    const el = document.createElement('div');
    el.className = 'runde' + (r.active ? ' active' : '');
    const count = (r.items?.length ?? 0) + (r.ratings?.length ?? 0);
    const destilledInfo = r.destilled?.length ? ` · ${r.destilled.length} destillerte` : '';
    el.innerHTML = `
      <div class="runde-head">
        <div><div class="runde-id">${id}</div><div class="runde-title">${r.title}</div></div>
        <div class="btns">
          <button class="btn primary" onclick="activate('${id}')">Aktiver</button>
          <button class="btn danger" onclick="clearR('${id}')">Tøm</button>
        </div>
      </div>
      <div class="runde-q">${r.question}</div>
      <div class="runde-count">${count} innspill${destilledInfo}</div>
    `;
    div.appendChild(el);
  }
}
async function activate(id) { await fetch('/api/round/' + id + '/activate', { method: 'POST' }); refresh(); }
async function clearR(id) { if (!confirm('Tøm ' + id + '?')) return; await fetch('/api/round/' + id + '/clear', { method: 'POST' }); refresh(); }
async function triggerAI(ep, label) {
  const r = await fetch(ep, { method: 'POST' });
  const data = await r.json();
  alert(label + ': ' + (data.meta?.ai_used ? 'Gemini' : 'fallback') + ' — se presentasjon');
}
refresh();
setInterval(refresh, 3000);
</script>
</body></html>"""


PARTICIPANT_HTML = """<!DOCTYPE html>
<html lang="nb"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bord — Strategiforum v3</title>
<link href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Public Sans", -apple-system, "Segoe UI", sans-serif; background: linear-gradient(135deg, #002547 0%, #000F1E 100%); color: #E8F0F5; min-height: 100vh; padding: 20px; }
.wrap { max-width: 640px; margin: 0 auto; }
h1 { color: #4FB3B6; font-size: 22px; margin-bottom: 4px; font-weight: 800; }
.sub { color: #A8BECE; font-size: 12px; margin-bottom: 18px; }
.status { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; color: #A8BECE; margin-bottom: 18px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #5BB67E; animation: pulse 2s infinite; }
@keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: .4 } }
.name-input { width: 100%; padding: 14px 18px; background: rgba(0, 48, 87, 0.55); border: 1px solid rgba(79, 179, 182, 0.22); color: #ffffff; font-size: 16px; border-radius: 10px; margin-bottom: 20px; font-family: inherit; }
.card { background: rgba(0, 48, 87, 0.55); border: 1px solid rgba(79, 179, 182, 0.22); border-radius: 14px; padding: 22px; }
.card .label { font-size: 11px; color: #4FB3B6; text-transform: uppercase; letter-spacing: 1.5px; font-weight: 700; margin-bottom: 8px; }
.card h2 { font-size: 20px; color: #ffffff; margin-bottom: 10px; font-weight: 700; }
.q { font-size: 15px; color: #A8BECE; margin-bottom: 16px; line-height: 1.5; }
textarea { width: 100%; padding: 14px; background: rgba(0,15,30,0.4); border: 1px solid rgba(79, 179, 182, 0.22); color: #ffffff; border-radius: 10px; font-size: 15px; font-family: inherit; resize: vertical; min-height: 90px; }
textarea:focus { outline: none; border-color: #4FB3B6; }
.submit { background: #4FB3B6; color: #001B35; border: none; padding: 14px 24px; border-radius: 10px; font-size: 15px; font-weight: 700; cursor: pointer; margin-top: 12px; width: 100%; font-family: inherit; }
.submit:hover { background: #6ED1D4; }
.submit:disabled { opacity: 0.5; cursor: not-allowed; }
.ratings { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin: 14px 0; }
.rating-btn { padding: 16px 0; background: rgba(0, 48, 87, 0.72); border: 2px solid rgba(79, 179, 182, 0.22); color: #ffffff; border-radius: 10px; font-size: 20px; font-weight: 700; cursor: pointer; font-family: inherit; }
.rating-btn.selected { background: #4FB3B6; color: #001B35; border-color: #4FB3B6; }
.cat-btns { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 14px 0; }
.cat-btn { padding: 12px; background: rgba(0, 48, 87, 0.72); border: 1px solid rgba(79, 179, 182, 0.22); color: #A8BECE; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600; font-family: inherit; }
.cat-btn.selected { background: #4FB3B6; color: #001B35; border-color: #4FB3B6; }
.pre-items { margin-top: 14px; padding: 12px; background: rgba(0,15,30,0.35); border-radius: 8px; border: 1px dashed rgba(79, 179, 182, 0.22); }
.pre-items h4 { font-size: 11px; color: #A8BECE; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
.pre-item { padding: 10px; background: rgba(255,255,255,0.03); border-left: 2px solid #4FB3B6; margin: 6px 0; font-size: 13px; border-radius: 0 6px 6px 0; }
.pre-item.sorted { opacity: 0.3; text-decoration: line-through; }
.pre-item .actions { margin-top: 6px; display: flex; gap: 4px; }
.pre-item .pre-cat-btn { flex: 1; padding: 5px 8px; font-size: 10px; border: 1px solid rgba(79, 179, 182, 0.22); background: transparent; color: #A8BECE; border-radius: 4px; cursor: pointer; font-family: inherit; }
.no-active { text-align: center; padding: 40px 20px; color: #A8BECE; }
.sent { background: rgba(91, 182, 126, 0.15); border: 1px solid #5BB67E; padding: 12px; border-radius: 8px; margin-top: 14px; font-size: 13px; color: #5BB67E; }
</style></head>
<body>
<div class="wrap">
  <h1>Strategiforum — Møteplasser</h1>
  <div class="sub">30. april 2026 · ett bord per laptop · sekretær legger inn gruppens svar</div>
  <div class="status"><span class="dot"></span><span id="status-text">Kobler til...</span></div>
  <input class="name-input" id="nameInput" placeholder='Navn på bordet (f.eks. "Bord 3")' />
  <div id="roundArea"></div>
</div>
<script>
let state = null;
let selectedRating = null;
let selectedCategory = null;
function getUserId() {
  let id = localStorage.getItem('nf_user_id');
  if (!id) { id = 'u_' + Math.random().toString(36).substr(2, 9); localStorage.setItem('nf_user_id', id); }
  return id;
}
function getUserName() { return document.getElementById('nameInput').value || localStorage.getItem('nf_user_name') || 'Anonym'; }
document.getElementById('nameInput').addEventListener('input', () => { localStorage.setItem('nf_user_name', document.getElementById('nameInput').value); });
document.getElementById('nameInput').value = localStorage.getItem('nf_user_name') || '';
let ws = null;
function connect() {
  const wsUrl = location.origin.replace(/^https?:/, location.protocol === 'https:' ? 'wss:' : 'ws:') + '/ws';
  ws = new WebSocket(wsUrl);
  ws.onopen = () => {
    document.getElementById('status-text').textContent = 'LIVE';
    ws.send(JSON.stringify({ type: 'register', user_id: getUserId(), user_name: getUserName() }));
  };
  ws.onmessage = (e) => { try { const msg = JSON.parse(e.data); if (msg.state) { state = msg.state; render(); } } catch (_) {} };
  ws.onclose = () => { document.getElementById('status-text').textContent = 'Frakoblet — prøver igjen'; setTimeout(connect, 2000); };
}
async function fetchState() { const r = await fetch('/api/state'); state = await r.json(); render(); }
function render() {
  const area = document.getElementById('roundArea');
  if (!state) return;
  const activeId = state.active_round;
  if (!activeId) { area.innerHTML = '<div class="card"><div class="no-active"><h2>Ingen aktiv runde</h2><p>Vent til Therese aktiverer neste runde.</p></div></div>'; return; }
  const round = state.rounds[activeId];
  if (!round) return;
  if (round.type === 'freetext') renderFreetext(activeId, round);
  else if (round.type === 'rating') renderRating(activeId, round);
  else if (round.type === 'categorized') renderCategorized(activeId, round);
}
function renderFreetext(id, round) {
  const mine = (round.items || []).find(it => it.user_id === getUserId());
  const area = document.getElementById('roundArea');
  area.innerHTML = `<div class="card"><div class="label">Aktiv runde</div><h2>${round.title}</h2><div class="q">${round.question}</div><textarea id="ftInput" placeholder="Gruppens svar">${mine ? mine.value : ''}</textarea><button class="submit" onclick="submitFreetext('${id}')">${mine ? 'Oppdater' : 'Send'}</button>${mine ? '<div class="sent">✓ Sendt.</div>' : ''}</div>`;
}
function submitFreetext(id) { const value = document.getElementById('ftInput').value.trim(); if (!value) return; ws.send(JSON.stringify({ type: 'submit_freetext', round_id: id, user_id: getUserId(), user_name: getUserName(), value: value })); }
function renderRating(id, round) {
  const mine = (round.ratings || []).find(r => r.user_id === getUserId());
  selectedRating = mine ? mine.value : null;
  const area = document.getElementById('roundArea');
  area.innerHTML = `<div class="card"><div class="label">Aktiv runde</div><h2>${round.title}</h2><div class="q">${round.question}</div><div class="ratings">${[1,2,3,4,5].map(v => `<button class="rating-btn ${selectedRating === v ? 'selected' : ''}" onclick="selectRating(${v})">${v}</button>`).join('')}</div><textarea id="ratingComment" placeholder="Kommentar (valgfritt)">${mine ? (mine.comment || '') : ''}</textarea><button class="submit" onclick="submitRating('${id}')">${mine ? 'Oppdater' : 'Send'}</button>${mine ? '<div class="sent">✓ Sendt.</div>' : ''}</div>`;
}
function selectRating(v) { selectedRating = v; document.querySelectorAll('.rating-btn').forEach((b, i) => b.classList.toggle('selected', i + 1 === v)); }
function submitRating(id) {
  if (!selectedRating) { alert('Velg 1-5'); return; }
  const comment = document.getElementById('ratingComment').value.trim();
  ws.send(JSON.stringify({ type: 'submit_rating', round_id: id, user_id: getUserId(), user_name: getUserName(), value: selectedRating, comment: comment }));
}
function renderCategorized(id, round) {
  const userId = getUserId();
  const cats = round.categories || [];
  const mineItems = (round.items || []).filter(it => it.user_id === userId);
  const preItems = round.pre_items || [];
  const sortedPre = new Set(mineItems.map(it => it.value));
  const area = document.getElementById('roundArea');
  area.innerHTML = `<div class="card"><div class="label">Aktiv runde</div><h2>${round.title}</h2><div class="q">${round.question}</div>${preItems.length ? `<div class="pre-items"><h4>Sorter disse byggene</h4>${preItems.map((p, i) => `<div class="pre-item ${sortedPre.has(p) ? 'sorted' : ''}" id="pre-${i}">${p}${!sortedPre.has(p) ? `<div class="actions">${cats.map(c => `<button class="pre-cat-btn" onclick="submitPre('${id}', ${i}, '${c}')">${c}</button>`).join('')}</div>` : ''}</div>`).join('')}</div>` : ''}<div style="margin-top: 16px;"><textarea id="catInput" placeholder="Skriv eget innspill her"></textarea><div class="cat-btns">${cats.map((c, i) => `<button class="cat-btn" onclick="selectCat(${i})">${c}</button>`).join('')}</div><button class="submit" onclick="submitCat('${id}')">Send</button></div></div>`;
  window.__preItems = preItems;
  window.__cats = cats;
  selectedCategory = null;
}
function selectCat(idx) { selectedCategory = window.__cats[idx]; document.querySelectorAll('.cat-btn').forEach((b, i) => b.classList.toggle('selected', i === idx)); }
function submitCat(id) {
  const value = document.getElementById('catInput').value.trim();
  if (!value || !selectedCategory) { alert('Skriv noe og velg kategori'); return; }
  ws.send(JSON.stringify({ type: 'submit_categorized', round_id: id, user_id: getUserId(), user_name: getUserName(), value: value, category: selectedCategory }));
  document.getElementById('catInput').value = '';
  selectedCategory = null;
  document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('selected'));
}
function submitPre(id, idx, cat) {
  const value = window.__preItems[idx];
  ws.send(JSON.stringify({ type: 'submit_categorized', round_id: id, user_id: getUserId(), user_name: getUserName(), value: value, category: cat }));
  document.getElementById('pre-' + idx)?.classList.add('sorted');
  const actions = document.querySelector('#pre-' + idx + ' .actions');
  if (actions) actions.remove();
}
fetchState();
connect();
</script>
</body></html>"""


WALL_HTML = """<!DOCTYPE html>
<html lang="nb"><head><meta charset="UTF-8">
<title>Live Wall — Strategiforum v3</title>
<link href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700&display=swap" rel="stylesheet">
<style>
body { font-family: "Public Sans", -apple-system, "Segoe UI", sans-serif; background: #001B35; color: #E8F0F5; margin: 0; padding: 30px; min-height: 100vh; }
h1 { color: #4FB3B6; font-size: 32px; margin-bottom: 20px; font-weight: 800; }
.active-info { background: rgba(0, 48, 87, 0.72); padding: 16px 24px; border-radius: 10px; border: 1px solid rgba(79, 179, 182, 0.22); margin-bottom: 24px; }
.active-info .id { font-family: ui-monospace, monospace; color: #6ED1D4; font-size: 11px; }
.active-info h2 { color: #ffffff; font-size: 24px; margin: 4px 0 6px; }
.active-info p { color: #A8BECE; font-size: 14px; }
.items { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
.item { background: rgba(79, 179, 182, 0.08); border-left: 3px solid #4FB3B6; padding: 14px 18px; border-radius: 4px 10px 10px 4px; font-size: 17px; }
.item .author { display: block; font-size: 10px; color: #A8BECE; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
</style></head>
<body>
<h1>Strategiforum v3 — Live Wall</h1>
<div id="content"></div>
<script>
async function refresh() {
  const r = await fetch('/api/state');
  const s = await r.json();
  const active = s.active_round;
  const c = document.getElementById('content');
  if (!active) { c.innerHTML = '<div class="active-info"><p>Ingen aktiv runde</p></div>'; return; }
  const round = s.rounds[active];
  const items = round.items || [];
  const ratings = round.ratings || [];
  let html = `<div class="active-info"><div class="id">${active}</div><h2>${round.title}</h2><p>${round.question}</p></div>`;
  if (items.length) {
    html += '<div class="items">' + items.map(it => `<div class="item">${esc(it.value)}${it.category ? ' <small>[' + it.category + ']</small>' : ''}<span class="author">${it.user_id || 'Anonym'}</span></div>`).join('') + '</div>';
  }
  if (ratings.length) {
    const avg = (ratings.reduce((a, r) => a + r.value, 0) / ratings.length).toFixed(1);
    html += `<p style="color:#6ED1D4;font-size:24px;margin-top:20px">Gjennomsnitt: ${avg}/5 (${ratings.length} grupper)</p>`;
  }
  c.innerHTML = html;
}
function esc(s) { return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
refresh();
setInterval(refresh, 2000);
</script>
</body></html>"""


# ====================================================================
# RUN
# ====================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"\nStrategiforum Workshop Server v3")
    print(f"=================================")
    print(f"Admin:    http://localhost:{port}/admin")
    print(f"Wall:     http://localhost:{port}/wall")
    print(f"Sekretær: http://localhost:{port}/p")
    print(f"LAN IP:   http://{get_local_ip()}:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
