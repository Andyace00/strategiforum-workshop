# Strategiforum 30. april 2026 — Møteplasser i Nordre Follo (v3)

Helt ny versjon bygget fra bunnen etter v2. Fire ting er grunnleggende annerledes:

1. **NFK Mørk visuell profil** — forankret i Nordre Follos designmanual (primary #001B35, container #003057, secondary teal #00696C, tertiary #4A7A96). Public Sans som hovedfont. Fraunces italic er fjernet fra all løpende tekst (dårlig lesbarhet på storskjerm) og beholdt KUN på monogrammer, chapter-nummer og evidens-tall der det gir karakter uten å koste lesbarhet.

2. **AI som rød tråd gjennom hele workshopen** — ikke bare runde 2. Gemini brukes fire steder, alle synlige for hele rommet (broadcastes via WebSocket):

   | Slide | AI-kall | Bruker som kontekst |
   |---|---|---|
   | 8 (r2) | `/api/destill-prinsipper` | r1-bildene + kartleggingsdata + r2-svar |
   | 19 (r6) | `/api/koble-dilemma` | dilemmaene + destillerte prinsipper + r5-sortering |
   | 21 (kd-setning) | `/api/kd-utkast` | prinsipper + Langhus-rating + satellitter + dilemmaer + konsensus |
   | 22 (avslutning) | `/api/sluttsyntese` | hele workshop-state komprimert til én setning |

   Øyvind kan redigere kd-utkastet direkte i slide 21 før han leser det opp. Fallbacks kjører automatisk hvis `GEMINI_API_KEY` mangler.

3. **Ekte NFK-bilder der de finnes, monogram + Imagen der de mangler** — slide 1 hero bruker Ski bibliotek som dempet bakgrunn, slide 5 bruker Kolben, slide 4 Asker-kort og KS-kort har verifiserte bilder. Lillestrøm-kortet er et monogram til vi har verifisert riktig pressebilde. `generer_bilder.py` genererer Imagen 4.0-bilder for slotsene vi mangler (Lillestrøm, Langhus-hypotese, hero).

4. **Server serverer hele presentasjonen** — `/show` leverer HTML, `/images/*` leverer bilder, `/nf_kart.html` leverer kart. WebSocket bruker samme origin — ingen hardkodet URL-oppdatering kreves når HTML åpnes fra Render-URLen.

## Filer

| Fil | Hensikt |
|---|---|
| `workshop_strategiforum.html` | Presentasjonen · 22 slides · NFK Mørk · AI-paneler |
| `workshop_server.py` | FastAPI · 7 runder · 4 Gemini-endepunkt · WebSocket · `/show` + `/images/` + `/healthz` |
| `workshop_context.json` | Domene · evidens · kartleggingsdata · tone · prompter |
| `nf_kart.html` | Leaflet-kart |
| `generer_bilder.py` | Imagen 4.0 bildegenerator for slots uten ekte bilder |
| `images/` | Ekte NFK-bilder (ski_1600, kolben_1600), verifiserte benchmark-bilder (asker, ks) |
| `requirements.txt` + `render.yaml` | Deploy |
| `.github/workflows/keepalive.yml` | Cron-ping hvert 10. min — hindrer Render-dvale |

## Deploy til Render (hovedmetode)

1. **Lag GitHub-repo** (f.eks. `strategiforum-workshop`)
   ```bash
   cd workshop_strategiforum_30april2026_v3
   git init
   git add .
   git commit -m "v3 — NFK Mørk, AI rød tråd, ekte bilder, server-levert presentasjon"
   gh repo create strategiforum-workshop --public --source=. --push
   ```

2. **Koble til Render**
   - https://dashboard.render.com → New → Web Service
   - Velg GitHub-repoet (eller pek på repo-URL)
   - Render leser `render.yaml` automatisk
   - Klikk Create Web Service

3. **Sett GEMINI_API_KEY** i Render Environment-fanen
   - Dashboard → Environment → Add → `GEMINI_API_KEY=...`
   - Redeploy

4. **Bruk**
   - `https://strategiforum-workshop.onrender.com/show` — presentasjon (gå fullskjerm, F11)
   - `https://strategiforum-workshop.onrender.com/admin` — fasilitator (Therese)
   - `https://strategiforum-workshop.onrender.com/p` — bord-sekretær (en per laptop)
   - `https://strategiforum-workshop.onrender.com/healthz` — health check

5. **Keepalive** — GitHub Action pinger `/healthz` hvert 10. min, hindrer dvale på free tier.

## Kjør lokalt (for testing)

```bash
cd workshop_strategiforum_30april2026_v3
pip install -r requirements.txt
export GEMINI_API_KEY=...   # valgfri; fallbacks brukes uten
python workshop_server.py
```

- Presentasjon: `http://localhost:8000/show`
- Admin: `http://localhost:8000/admin`
- Bord: `http://localhost:8000/p`

Hvis du vil åpne HTML-filen direkte i nettleseren uten server: legg til `?local` i URL-en (`workshop_strategiforum.html?local`) — da kobler den til `localhost:8000`.

## Generer bilder med Imagen

```bash
export GEMINI_API_KEY=...
python generer_bilder.py              # alle slots
python generer_bilder.py lillestrom   # bare én
```

Genererer til `images/`-mappa. Kjør igjen og erstatt resultatet manuelt hvis det ikke er bra nok. For Lillestrøm: helst hent verifisert pressebilde fra `lillestrombibliotekene.no` før 30/4 — Imagen er fallback.

## Tastatur i presentasjonen

- `→` / `Space` / `PageDown` — neste slide
- `←` / `PageUp` — forrige slide
- `F` — toggle fasilitatornoter
- `Home` / `End` — første / siste slide

## Status før 30. april

- [x] NFK Mørk visuell profil
- [x] AI-flyt for r2, r6, r21, r22
- [x] Ekte bilder for Ski, Kolbotn, Asker, KS
- [x] Server-levert presentasjon + assets
- [x] Render-deploy-config + keepalive
- [x] Alle Thereses korrigeringer fra 14/4 bevart
- [ ] Deploy til Render + sett GEMINI_API_KEY
- [ ] Generer Lillestrøm-bildet (eller hent verifisert pressefoto)
- [ ] Kvm-tall bekreftes av Eiendom
- [ ] Prøvekjøring med 3–4 personer senest uka før
- [ ] Brief Therese + Øyvind 45 min før dagen

## Backup

v2 ligger urørt i `../workshop_strategiforum_30april2026_v2/`. v3 er en fullstendig ny versjon — ingen patcher på v2.
