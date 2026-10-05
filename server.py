from flask import Flask, request, jsonify

import json

import os

import uuid

import random

import threading

import time

import requests
import hashlib
import secrets



app = Flask(__name__)



SKRIPT_ORDNER = os.path.dirname(os.path.abspath(__file__))

DATEINAME = os.path.join(SKRIPT_ORDNER, "server_quizze.json")



# Duellräume liegen absichtlich nur im Arbeitsspeicher.

# Bei einem Server-Neustart verschwinden laufende Räume.

DUELLE = {}

DUELL_LOCK = threading.Lock()

# Kurzlebige Spiel-Sitzungen verhindern, dass Ergebnisse einfach per API hochgezählt werden.
PLAY_SESSIONS = {}
PLAY_LOCK = threading.Lock()
PLAY_SESSION_TTL = 3 * 60 * 60

MELDUNGEN_DATEI = os.path.join(SKRIPT_ORDNER, "server_meldungen.json")






def quizze_laden():

    if os.path.exists(DATEINAME):

        with open(DATEINAME, "r", encoding="utf-8") as datei:

            return json.load(datei)

    return []





def quizze_speichern(quizze):

    with open(DATEINAME, "w", encoding="utf-8") as datei:

        json.dump(quizze, datei, ensure_ascii=False, indent=2)





def quiz_finden(quizze, quiz_id):

    for quiz in quizze:

        if str(quiz.get("id")) == str(quiz_id):

            return quiz

    return None





def sichere_geheimnis_pruefung(empfangen, erwartet):
    """Vergleicht geheime Tokens ohne frühes Abbrechen beim ersten Unterschied."""
    empfangen = str(empfangen or "")
    erwartet = str(erwartet or "")
    return bool(erwartet) and secrets.compare_digest(empfangen, erwartet)


def quiz_eingaben_pruefen(daten):
    """Kleine serverseitige Größen-/Typprüfung gegen kaputte oder riesige Requests."""
    if not isinstance(daten, dict):
        return "Ungültige Daten."
    titel = daten.get("titel")
    fragen = daten.get("fragen")
    if not isinstance(titel, str) or not (1 <= len(titel.strip()) <= 120):
        return "Der Quiztitel muss 1 bis 120 Zeichen lang sein."
    if not isinstance(fragen, list) or len(fragen) > 100:
        return "Ein Quiz darf höchstens 100 Fragen enthalten."
    for eintrag in fragen:
        if not isinstance(eintrag, dict):
            return "Ungültiges Fragenformat."
        frage = eintrag.get("frage")
        antwort = eintrag.get("antwort")
        if not isinstance(frage, str) or not isinstance(antwort, str):
            return "Frage und Antwort müssen Text sein."
        if not frage.strip() or not antwort.strip() or len(frage) > 1000 or len(antwort) > 1000:
            return "Frage und Antwort müssen 1 bis 1000 Zeichen lang sein."
    token = str(daten.get("owner_token", ""))
    if token and not (32 <= len(token) <= 256):
        return "Ungültige Besitzerkennung."
    return None


RANG_STUFEN = [(0,"🌱 Anfänger"),(500,"🎓 Schüler"),(1500,"🧠 Kenner"),(3500,"⭐ Experte"),(7000,"🏅 Master"),(12000,"🔬 Professor"),(20000,"💎 Wissenselite"),(35000,"🌌 Universalgenie")]

def rang_fuer_xp(xp):
    try: xp=max(0,min(int(xp),1000000))
    except (TypeError,ValueError): xp=0
    rang=RANG_STUFEN[0][1]
    for grenze,name in RANG_STUFEN:
        if xp>=grenze: rang=name
    return rang

def oeffentliche_ansicht(quiz):

    return {

        "id": quiz.get("id"),

        "titel": quiz.get("titel"),

        "fragen": quiz.get("fragen", []),

        "ersteller": quiz.get("ersteller", "Unbekannt"),
        "rang": quiz.get("rang", "🌱 Anfänger"),
        "theme": quiz.get("theme", "auto"),
        "sprache": quiz.get("sprache", "de"),
        "spiele": int(quiz.get("spiele", 0)),
        "abgeschlossen": int(quiz.get("abgeschlossen", 0)),
        "durchschnitt": round(float(quiz.get("summe_prozent", 0)) / max(1, int(quiz.get("abgeschlossen", 0)))) if int(quiz.get("abgeschlossen", 0)) else 0

    }





@app.route("/quizze", methods=["GET"])

def alle_quizze_abrufen():

    quizze = quizze_laden()

    return jsonify([oeffentliche_ansicht(q) for q in quizze])





@app.route("/quizze/<quiz_id>", methods=["GET"])

def ein_quiz_abrufen(quiz_id):

    quizze = quizze_laden()

    quiz = quiz_finden(quizze, quiz_id)

    if quiz:

        return jsonify(oeffentliche_ansicht(quiz))

    return jsonify({"fehler": "Quiz nicht gefunden"}), 404





@app.route("/quizze", methods=["POST"])

def quiz_veroeffentlichen():

    daten = request.get_json(silent=True)

    if not daten or "titel" not in daten or "fragen" not in daten:

        return jsonify({"fehler": "Titel und Fragen sind erforderlich"}), 400

    fehler = quiz_eingaben_pruefen(daten)
    if fehler:
        return jsonify({"fehler": fehler}), 400

    quizze = quizze_laden()

    neues_quiz = {

        "id": uuid.uuid4().hex[:8],

        "titel": daten["titel"],

        "fragen": daten["fragen"],

        "owner_token": daten.get("owner_token", ""),

        "ersteller": str(daten.get("ersteller", "Unbekannt")).strip()[:30] or "Unbekannt",
        "rang": rang_fuer_xp(daten.get("xp", 0)),
        "theme": str(daten.get("theme", "auto")).strip()[:30] or "auto",
        "sprache": str(daten.get("sprache", "de")).strip()[:8] or "de",
        "spiele": 0,
        "abgeschlossen": 0,
        "summe_prozent": 0,
        "uebersetzungen": {}

    }

    quizze.append(neues_quiz)

    quizze_speichern(quizze)

    return jsonify(oeffentliche_ansicht(neues_quiz)), 201





@app.route("/quizze/<quiz_id>", methods=["PUT"])

def quiz_aktualisieren(quiz_id):

    daten = request.get_json(silent=True)

    if not daten:

        return jsonify({"fehler": "Keine Daten erhalten"}), 400



    quizze = quizze_laden()

    quiz = quiz_finden(quizze, quiz_id)

    if not quiz:

        return jsonify({"fehler": "Quiz nicht gefunden"}), 404

    if not sichere_geheimnis_pruefung(daten.get("owner_token"), quiz.get("owner_token")):

        return jsonify({"fehler": "Keine Berechtigung für dieses Quiz"}), 403

    pruef_daten = {
        "titel": daten.get("titel", quiz.get("titel", "")),
        "fragen": daten.get("fragen", quiz.get("fragen", [])),
        "owner_token": daten.get("owner_token", "")
    }
    fehler = quiz_eingaben_pruefen(pruef_daten)
    if fehler:
        return jsonify({"fehler": fehler}), 400

    if "titel" in daten:

        quiz["titel"] = daten["titel"]

    if "fragen" in daten:

        quiz["fragen"] = daten["fragen"]

    if "ersteller" in daten:

        quiz["ersteller"] = str(daten["ersteller"]).strip()[:30] or "Unbekannt"

    if "theme" in daten:

        quiz["theme"] = str(daten["theme"]).strip()[:30] or "auto"
    if "sprache" in daten:
        quiz["sprache"] = str(daten["sprache"]).strip()[:8] or "de"
    if "xp" in daten:
        quiz["rang"] = rang_fuer_xp(daten.get("xp", 0))
    if "titel" in daten or "fragen" in daten or "sprache" in daten:
        quiz["uebersetzungen"] = {}



    quizze_speichern(quizze)

    return jsonify(oeffentliche_ansicht(quiz))





def _alte_spiel_sitzungen_loeschen():
    grenze = time.time() - PLAY_SESSION_TTL
    for token in list(PLAY_SESSIONS):
        if PLAY_SESSIONS[token].get("erstellt", 0) < grenze:
            PLAY_SESSIONS.pop(token, None)


@app.route("/quizze/<quiz_id>/start", methods=["POST"])
def quiz_spiel_start(quiz_id):
    quizze = quizze_laden(); quiz = quiz_finden(quizze, quiz_id)
    if not quiz: return jsonify({"fehler": "Quiz nicht gefunden"}), 404
    quiz["spiele"] = int(quiz.get("spiele", 0)) + 1
    quizze_speichern(quizze)
    with PLAY_LOCK:
        _alte_spiel_sitzungen_loeschen()
        spiel_token = secrets.token_urlsafe(24)
        PLAY_SESSIONS[spiel_token] = {"quiz_id": str(quiz_id), "erstellt": time.time(), "benutzt": False}
    return jsonify({"spiele": quiz["spiele"], "spiel_token": spiel_token})


@app.route("/quizze/<quiz_id>/ergebnis", methods=["POST"])
def quiz_ergebnis(quiz_id):
    daten = request.get_json(silent=True) or {}
    try: prozent = max(0, min(100, int(daten.get("prozent"))))
    except (TypeError, ValueError): return jsonify({"fehler": "Ungültiges Ergebnis"}), 400
    spiel_token = str(daten.get("spiel_token", "")).strip()
    with PLAY_LOCK:
        _alte_spiel_sitzungen_loeschen()
        sitzung = PLAY_SESSIONS.get(spiel_token)
        if not sitzung or sitzung.get("benutzt") or sitzung.get("quiz_id") != str(quiz_id):
            return jsonify({"fehler": "Ungültige oder bereits verwendete Spiel-Sitzung."}), 403
        sitzung["benutzt"] = True
    quizze = quizze_laden(); quiz = quiz_finden(quizze, quiz_id)
    if not quiz: return jsonify({"fehler": "Quiz nicht gefunden"}), 404
    quiz["abgeschlossen"] = int(quiz.get("abgeschlossen", 0)) + 1
    quiz["summe_prozent"] = int(quiz.get("summe_prozent", 0)) + prozent
    quizze_speichern(quizze)
    return jsonify(oeffentliche_ansicht(quiz))


def meldungen_laden():
    if os.path.exists(MELDUNGEN_DATEI):
        try:
            with open(MELDUNGEN_DATEI, "r", encoding="utf-8") as datei:
                daten = json.load(datei)
                return daten if isinstance(daten, list) else []
        except (OSError, ValueError, TypeError):
            return []
    return []


def meldungen_speichern(meldungen):
    with open(MELDUNGEN_DATEI, "w", encoding="utf-8") as datei:
        json.dump(meldungen, datei, ensure_ascii=False, indent=2)


@app.route("/quizze/<quiz_id>/melden", methods=["POST"])
def quiz_melden(quiz_id):
    daten = request.get_json(silent=True) or {}
    grund = str(daten.get("grund", "")).strip()[:300]
    if len(grund) < 5:
        return jsonify({"fehler": "Bitte beschreibe den Grund kurz."}), 400
    quiz = quiz_finden(quizze_laden(), quiz_id)
    if not quiz:
        return jsonify({"fehler": "Quiz nicht gefunden"}), 404
    geraet = request.headers.get("X-Device-Token", "").strip()
    if not geraet:
        return jsonify({"fehler": "Gerätekennung fehlt."}), 400
    geraet_hash = hashlib.sha256(geraet.encode("utf-8")).hexdigest()
    meldungen = meldungen_laden()
    if any(str(m.get("quiz_id")) == str(quiz_id) and m.get("geraet_hash") == geraet_hash and m.get("status") == "offen" for m in meldungen):
        return jsonify({"fehler": "Du hast dieses Quiz bereits gemeldet."}), 409
    meldung = {
        "id": uuid.uuid4().hex[:10], "quiz_id": str(quiz_id),
        "quiz_titel": str(quiz.get("titel", "Ohne Titel"))[:100],
        "grund": grund, "geraet_hash": geraet_hash, "status": "offen",
        "zeit": time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    }
    meldungen.append(meldung); meldungen_speichern(meldungen)
    return jsonify({"erfolg": True, "meldung": "Danke. Die Meldung wurde an den Operator gesendet."}), 201


@app.route("/quizze/<quiz_id>", methods=["DELETE"])

def quiz_loeschen(quiz_id):

    daten = request.get_json(silent=True) or {}

    quizze = quizze_laden()

    quiz = quiz_finden(quizze, quiz_id)



    if not quiz:

        return jsonify({"fehler": "Quiz nicht gefunden"}), 404

    if not sichere_geheimnis_pruefung(daten.get("owner_token"), quiz.get("owner_token")):

        return jsonify({"fehler": "Keine Berechtigung für dieses Quiz"}), 403



    quizze = [q for q in quizze if str(q.get("id")) != str(quiz_id)]

    quizze_speichern(quizze)

    return jsonify({"erfolg": True})







# -------------------- KI-QUIZ (GEMINI) --------------------



GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

GEMINI_MODELL = os.environ.get("GEMINI_MODELL", "gemini-3.5-flash-lite").strip()

# Nur Modelle, deren Standard-Textnutzung laut Gemini-Preisseite im Free Tier

# kostenlos angeboten wird. Reihenfolge: leicht/schnell zuerst, danach weitere

# stabile Flash-Modelle als Ausweichmoeglichkeit bei 429/503.

GEMINI_KOSTENLOSE_FALLBACKS = [

    "gemini-3.1-flash-lite",

    "gemini-3.5-flash",

    "gemini-3.6-flash",

    "gemini-3.7-flash",

    "gemini-3.8-flash",

]





@app.route("/quizze/<quiz_id>/uebersetzen", methods=["POST"])
def quiz_uebersetzen_route(quiz_id):
    daten = request.get_json(silent=True) or {}
    ziel = str(daten.get("ziel", "")).strip().lower()[:8]
    force = bool(daten.get("force", False))
    erlaubte = {"de":"Deutsch", "en":"Englisch", "es":"Spanisch", "fr":"Französisch", "it":"Italienisch"}
    if ziel not in erlaubte: return jsonify({"fehler":"Sprache nicht unterstützt."}), 400
    quizze=quizze_laden(); quiz=quiz_finden(quizze, quiz_id)
    if not quiz: return jsonify({"fehler":"Quiz nicht gefunden"}), 404
    # Ältere Quizze können eine falsche Sprach-Markierung besitzen. Bei force
    # wird der Inhalt deshalb trotzdem von Gemini in die Zielsprache übertragen.
    if ziel == str(quiz.get("sprache","de")) and not force:
        return jsonify({"titel":quiz.get("titel",""), "fragen":quiz.get("fragen",[]), "sprache":ziel, "automatisch_uebersetzt":False})
    cache=quiz.setdefault("uebersetzungen", {})
    # force bedeutet: Inhalt wirklich neu in die gewünschte Sprache übersetzen.
    # Dadurch werden auch alte/falsch markierte Quizze korrigiert und ein
    # veralteter Cache kann nicht wieder deutsche Fragen/Antworten liefern.
    if ziel in cache and not force:
        return jsonify(cache[ziel])
    if not GEMINI_API_KEY: return jsonify({"fehler":"Übersetzung ist gerade nicht verfügbar."}), 503
    schema={"type":"OBJECT","properties":{"titel":{"type":"STRING"},"fragen":{"type":"ARRAY","items":{"type":"OBJECT","properties":{"frage":{"type":"STRING"},"antwort":{"type":"STRING"}},"required":["frage","antwort"]}}},"required":["titel","fragen"]}
    prompt=(f"Übersetze dieses Quiz vollständig ins {erlaubte[ziel]}. Bewahre Bedeutung und Schwierigkeit. "
            "Übersetze Titel, Fragen und Antworten. Bei Eigennamen und Fachbegriffen bleibe sachlich. Gib nur das geforderte JSON zurück.\n" +
            json.dumps({"titel":quiz.get("titel",""),"fragen":quiz.get("fragen",[])}, ensure_ascii=False))
    try:
        url=f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODELL}:generateContent"
        r=requests.post(url,headers={"x-goog-api-key":GEMINI_API_KEY,"Content-Type":"application/json"},json={"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"responseMimeType":"application/json","responseSchema":schema}},timeout=60)
        if not r.ok: return jsonify({"fehler":"Übersetzung konnte nicht erstellt werden."}), 502
        roh=r.json(); teile=roh.get("candidates",[{}])[0].get("content",{}).get("parts",[])
        ergebnis=json.loads("".join(str(t.get("text","")) for t in teile))
        if len(ergebnis.get("fragen",[])) != len(quiz.get("fragen",[])): return jsonify({"fehler":"Übersetzung war unvollständig."}), 502
        out={"titel":str(ergebnis.get("titel",quiz.get("titel","")))[:100],"fragen":ergebnis["fragen"],"sprache":ziel,"automatisch_uebersetzt":True}
        cache[ziel]=out; quizze_speichern(quizze); return jsonify(out)
    except (requests.exceptions.RequestException, ValueError, TypeError, IndexError, KeyError):
        return jsonify({"fehler":"Übersetzung konnte gerade nicht erstellt werden."}), 502



@app.route("/uebersetzen-inhalt", methods=["POST"])
def inhalt_uebersetzen_route():
    """Übersetzt einen beliebigen Quiz-Inhalt (lokal, Special oder öffentlich)."""
    daten = request.get_json(silent=True) or {}
    ziel = str(daten.get("ziel", "")).strip().lower()[:8]
    erlaubte = {"de":"Deutsch", "en":"Englisch", "es":"Spanisch", "fr":"Französisch", "it":"Italienisch"}
    if ziel not in erlaubte:
        return jsonify({"fehler":"Sprache nicht unterstützt."}), 400
    titel = str(daten.get("titel", "")).strip()[:100]
    fragen = daten.get("fragen", [])
    if not isinstance(fragen, list) or not fragen:
        return jsonify({"fehler":"Keine Fragen zum Übersetzen vorhanden."}), 400
    if not GEMINI_API_KEY:
        return jsonify({"fehler":"Übersetzung ist gerade nicht verfügbar."}), 503
    schema={"type":"OBJECT","properties":{"titel":{"type":"STRING"},"fragen":{"type":"ARRAY","items":{"type":"OBJECT","properties":{"frage":{"type":"STRING"},"antwort":{"type":"STRING"}},"required":["frage","antwort"]}}},"required":["titel","fragen"]}
    prompt=(f"Übertrage dieses Quiz vollständig und ausschließlich ins {erlaubte[ziel]}. "
            "Jede Frage und jede erwartete Antwort muss in dieser Zielsprache stehen. "
            "Eine Antwort in einer anderen Sprache soll nicht als alternative Lösung ergänzt werden. "
            "Eigennamen dürfen unverändert bleiben. Gib nur das geforderte JSON zurück.\n" +
            json.dumps({"titel":titel,"fragen":fragen}, ensure_ascii=False))
    try:
        url=f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODELL}:generateContent"
        r=requests.post(url,headers={"x-goog-api-key":GEMINI_API_KEY,"Content-Type":"application/json"},json={"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"responseMimeType":"application/json","responseSchema":schema}},timeout=60)
        if not r.ok:
            return jsonify({"fehler":"Übersetzung konnte nicht erstellt werden."}), 502
        roh=r.json(); teile=roh.get("candidates",[{}])[0].get("content",{}).get("parts",[])
        ergebnis=json.loads("".join(str(t.get("text","")) for t in teile))
        if len(ergebnis.get("fragen",[])) != len(fragen):
            return jsonify({"fehler":"Übersetzung war unvollständig."}), 502
        return jsonify({"titel":str(ergebnis.get("titel",titel))[:100],"fragen":ergebnis["fragen"],"sprache":ziel,"automatisch_uebersetzt":True})
    except (requests.exceptions.RequestException, ValueError, TypeError, IndexError, KeyError):
        return jsonify({"fehler":"Übersetzung konnte gerade nicht erstellt werden."}), 502


@app.route("/ki-quiz", methods=["POST"])

def ki_quiz_erstellen_route():

    daten = request.get_json(silent=True) or {}

    thema = str(daten.get("thema", "")).strip()[:120]

    schwierigkeit = str(daten.get("schwierigkeit", "Mittel")).strip()[:20]
    ziel_code = str(daten.get("sprache", "de")).strip().lower()[:8]
    sprach_namen = {"de":"Deutsch", "en":"Englisch", "fr":"Französisch", "es":"Spanisch", "it":"Italienisch"}
    ziel_sprache = sprach_namen.get(ziel_code, "Deutsch")

    try:

        anzahl = int(daten.get("anzahl", 10))

    except (TypeError, ValueError):

        anzahl = 10

    anzahl = max(3, min(20, anzahl))



    if len(thema) < 2:

        return jsonify({"fehler": "Bitte gib ein Thema ein."}), 400

    if not GEMINI_API_KEY:

        return jsonify({"fehler": "Gemini ist auf dem Server noch nicht eingerichtet."}), 503



    schema = {

        "type": "OBJECT",

        "properties": {

            "titel": {"type": "STRING"},

            "fragen": {

                "type": "ARRAY",

                "minItems": anzahl,

                "maxItems": anzahl,

                "items": {

                    "type": "OBJECT",

                    "properties": {

                        "frage": {"type": "STRING"},

                        "antwort": {"type": "STRING"},

                        "falsche_optionen": {
                            "type": "ARRAY",
                            "minItems": 3,
                            "maxItems": 3,
                            "items": {"type": "STRING"}
                        }

                    },

                    "required": ["frage", "antwort", "falsche_optionen"]

                }

            }

        },

        "required": ["titel", "fragen"]

    }



    prompt = (

        f"Erstelle ein Quiz vollständig auf {ziel_sprache} zum Thema: {thema!r}. "

        f"Schwierigkeit: {schwierigkeit}. Genau {anzahl} Fragen. "

        "Die Fragen sollen eindeutig, sachlich und für Jugendliche geeignet sein. "

        "Jede Frage braucht eine kurze, eindeutig prüfbare richtige Antwort. "

        "Erzeuge danach genau drei plausible falsche Antwortmöglichkeiten im Feld falsche_optionen. "

        "WICHTIG: Verändere die richtige Antwort beim Erzeugen der falschen Möglichkeiten nicht. "

        "Die drei falschen Möglichkeiten dürfen weder identisch noch nur eine andere Schreibweise der richtigen Antwort sein. "

        "Der Server fügt die richtige Antwort anschließend selbst zu den drei falschen Möglichkeiten hinzu. "

        "Nutze natürliche Formulierungen, damit keine freie Texteingabe "

        "nötig ist. Vermeide gefährliche Anleitungen, sexuelle Inhalte "

        "und andere nicht altersgerechte Inhalte. Die Lösungen dürfen nicht in den Fragen verraten werden."

    )



    try:

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODELL}:generateContent"

        anfrage_daten = {

            "contents": [{"parts": [{"text": prompt}]}],

            "generationConfig": {

                "responseMimeType": "application/json",

                "responseSchema": schema

            }

        }



        # Erst das bevorzugte Modell versuchen, danach mehrere kostenlose

        # stabile Flash-Modelle. So hat das Quiz bei temporaerer Auslastung

        # eines einzelnen Modells eine deutlich bessere Chance.

        antwort = None

        verwendetes_modell = None

        modelle = []

        for modell in [GEMINI_MODELL] + GEMINI_KOSTENLOSE_FALLBACKS:

            if modell and modell not in modelle:

                modelle.append(modell)



        # Zwei Versuche je Modell: genug fuer einen kurzen 503/429-Spike,

        # ohne den Nutzer bei sechs Modellen minutenlang warten zu lassen.

        wartezeiten = [0, 2]

        for modell in modelle:

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modell}:generateContent"



            for versuch, wartezeit in enumerate(wartezeiten, start=1):

                if wartezeit:

                    time.sleep(wartezeit)



                antwort = requests.post(

                    url,

                    headers={

                        "x-goog-api-key": GEMINI_API_KEY,

                        "Content-Type": "application/json"

                    },

                    json=anfrage_daten,

                    timeout=60

                )



                if antwort.ok:

                    verwendetes_modell = modell

                    print(f"Gemini-Erfolg mit Modell: {modell}")

                    break



                print(

                    f"Gemini-Fehler {modell} (Versuch {versuch}/{len(wartezeiten)}):",

                    antwort.status_code,

                    antwort.text[:1500]

                )



                # Nur bei vorübergehender Überlastung weiter versuchen/ausweichen.

                if antwort.status_code not in (429, 503):

                    break



            if antwort is not None and antwort.ok:

                break



            # Bei einem dauerhaften Fehler (z. B. 400/403/404) nicht blind

            # weitere Modelle probieren.

            if antwort is not None and antwort.status_code not in (429, 503):

                break



        if not antwort.ok:

            if antwort.status_code in (429, 503):

                return jsonify({

                    "fehler": (

                        "Das KI-Quiz konnte aufgrund einer vorübergehend zu hohen "

                        "Serverauslastung nicht erstellt werden. Bitte versuche es in Kürze erneut."

                    )

                }), 503

            return jsonify({

                "fehler": "Das KI-Quiz konnte wegen eines Fehlers beim KI-Dienst nicht erstellt werden."

            }), 502



        roh = antwort.json()

        kandidaten = roh.get("candidates", [])

        if not kandidaten:

            print("Gemini-Fehler: keine Kandidaten", str(roh)[:1500])

            return jsonify({"fehler": "Gemini hat kein Quiz geliefert."}), 502



        teile = kandidaten[0].get("content", {}).get("parts", [])

        text = "".join(str(t.get("text", "")) for t in teile).strip()

        quiz = json.loads(text)



        fragen = quiz.get("fragen", [])

        if len(fragen) != anzahl:

            return jsonify({"fehler": "Die KI hat kein vollständiges Quiz geliefert."}), 502



        sauber = []

        for frage in fragen:

            frage_text = str(frage.get("frage", "")).strip()

            antwort_text = str(frage.get("antwort", "")).strip()

            falsche_optionen = [str(x).strip() for x in frage.get("falsche_optionen", []) if str(x).strip()]
            if not frage_text or not antwort_text or len(falsche_optionen) != 3:
                return jsonify({"fehler": "Die KI hat eine unvollständige Frage geliefert."}), 502

            # Die KI erzeugt nur die drei falschen Möglichkeiten. Die richtige
            # Antwort wird unverändert vom Server ergänzt.
            if any(x.casefold() == antwort_text.casefold() for x in falsche_optionen):
                return jsonify({"fehler": "Die KI hat die richtige Antwort als falsche Möglichkeit wiederholt."}), 502
            if len({x.casefold() for x in falsche_optionen}) != 3:
                return jsonify({"fehler": "Die KI hat doppelte Antwortmöglichkeiten geliefert."}), 502

            optionen = [antwort_text] + falsche_optionen
            random.shuffle(optionen)
            sauber.append({"frage": frage_text, "antwort": antwort_text, "optionen": optionen})


        return jsonify({

            "titel": str(quiz.get("titel") or f"KI-Quiz: {thema}").strip()[:80],

            "fragen": sauber

        })

    except (requests.exceptions.RequestException, ValueError, TypeError, KeyError, IndexError) as fehler:

        print("Gemini-KI-Quiz-Fehler:", fehler)

        return jsonify({"fehler": "Das KI-Quiz konnte gerade nicht erstellt werden."}), 502





\
# -------------------- OPERATOR-SPECIALS --------------------

SPECIAL_DATEI = os.path.join(SKRIPT_ORDNER, "server_specials.json")
OPERATOR_KEY = os.environ.get("OPERATOR_KEY", "").strip()
OPERATOR_DEVICE_TOKEN = os.environ.get("OPERATOR_DEVICE_TOKEN", "").strip()


def specials_laden():
    if os.path.exists(SPECIAL_DATEI):
        try:
            with open(SPECIAL_DATEI, "r", encoding="utf-8") as datei:
                daten = json.load(datei)
                return daten if isinstance(daten, list) else []
        except (OSError, ValueError, TypeError):
            return []
    return []


def specials_speichern(specials):
    with open(SPECIAL_DATEI, "w", encoding="utf-8") as datei:
        json.dump(specials, datei, ensure_ascii=False, indent=2)


def operator_erlaubt():
    schluessel = request.headers.get("X-Operator-Key", "").strip()
    geraet = request.headers.get("X-Device-Token", "").strip()
    key_ok = sichere_geheimnis_pruefung(schluessel, OPERATOR_KEY)
    geraet_ok = sichere_geheimnis_pruefung(geraet, OPERATOR_DEVICE_TOKEN)
    return key_ok or geraet_ok


@app.route("/operator/status", methods=["GET"])
def operator_status():
    geraet = request.headers.get("X-Device-Token", "").strip()
    return jsonify({
        "operator": sichere_geheimnis_pruefung(geraet, OPERATOR_DEVICE_TOKEN)
    })


@app.route("/operator/meldungen", methods=["GET"])
def operator_meldungen():
    if not operator_erlaubt():
        return jsonify({"fehler": "Keine Operator-Berechtigung."}), 403
    return jsonify([{k:v for k,v in m.items() if k != "geraet_hash"} for m in meldungen_laden()])


@app.route("/operator/meldungen/<meldung_id>", methods=["DELETE"])
def operator_meldung_erledigen(meldung_id):
    if not operator_erlaubt():
        return jsonify({"fehler": "Keine Operator-Berechtigung."}), 403
    meldungen = meldungen_laden()
    neu = [m for m in meldungen if str(m.get("id")) != str(meldung_id)]
    if len(neu) == len(meldungen):
        return jsonify({"fehler": "Meldung nicht gefunden."}), 404
    meldungen_speichern(neu)
    return jsonify({"erfolg": True})


def special_oeffentlich(special):
    return {
        "id": special.get("id"),
        "titel": special.get("titel", "Special Quiz"),
        "beschreibung": special.get("beschreibung", ""),
        "fragen": special.get("fragen", []),
        "theme": special.get("theme", "special"),
        "emoji": special.get("emoji", "⭐"),
        "start": special.get("start", ""),
        "ende": special.get("ende", ""),
        "aktiv": bool(special.get("aktiv", True)),
        "sprache": special.get("sprache", "de")
    }


def special_ist_aktuell(special):
    if not special.get("aktiv", True):
        return False
    heute = time.strftime("%Y-%m-%d", time.gmtime())
    start = str(special.get("start", "")).strip()
    ende = str(special.get("ende", "")).strip()
    if start and heute < start:
        return False
    if ende and heute > ende:
        return False
    return True


@app.route("/specials", methods=["GET"])
def specials_abrufen():
    specials = specials_laden()
    return jsonify([special_oeffentlich(s) for s in specials if special_ist_aktuell(s)])


@app.route("/operator/specials", methods=["GET"])
def operator_specials_auflisten():
    if not operator_erlaubt():
        return jsonify({"fehler": "Keine Operator-Berechtigung."}), 403
    return jsonify([special_oeffentlich(s) for s in specials_laden()])


@app.route("/operator/specials", methods=["POST"])
def operator_special_erstellen():
    if not operator_erlaubt():
        return jsonify({"fehler": "Keine Operator-Berechtigung."}), 403
    daten = request.get_json(silent=True) or {}
    titel = str(daten.get("titel", "")).strip()[:80]
    fragen = daten.get("fragen", [])
    if not titel or not isinstance(fragen, list) or not fragen:
        return jsonify({"fehler": "Titel und mindestens eine Frage sind erforderlich."}), 400
    special = {
        "id": uuid.uuid4().hex[:8],
        "titel": titel,
        "beschreibung": str(daten.get("beschreibung", "")).strip()[:220],
        "fragen": fragen[:30],
        "theme": str(daten.get("theme", "special")).strip()[:30] or "special",
        "emoji": str(daten.get("emoji", "⭐")).strip()[:4] or "⭐",
        "start": str(daten.get("start", "")).strip()[:10],
        "ende": str(daten.get("ende", "")).strip()[:10],
        "aktiv": bool(daten.get("aktiv", True)),
        "sprache": str(daten.get("sprache", "de")).strip()[:8] or "de"
    }
    specials = specials_laden()
    specials.append(special)
    specials_speichern(specials)
    return jsonify(special_oeffentlich(special)), 201


@app.route("/operator/specials/<special_id>", methods=["PUT", "DELETE"])
def operator_special_aendern(special_id):
    if not operator_erlaubt():
        return jsonify({"fehler": "Keine Operator-Berechtigung."}), 403
    specials = specials_laden()
    special = next((s for s in specials if str(s.get("id")) == str(special_id)), None)
    if not special:
        return jsonify({"fehler": "Special nicht gefunden."}), 404
    if request.method == "DELETE":
        specials = [s for s in specials if str(s.get("id")) != str(special_id)]
        specials_speichern(specials)
        return jsonify({"erfolg": True})
    daten = request.get_json(silent=True) or {}
    for feld in ("titel", "beschreibung", "theme", "emoji", "start", "ende", "aktiv"):
        if feld in daten:
            special[feld] = daten[feld]
    if "fragen" in daten and isinstance(daten["fragen"], list) and daten["fragen"]:
        special["fragen"] = daten["fragen"][:30]
    specials_speichern(specials)
    return jsonify(special_oeffentlich(special))


# -------------------- MEHRSPIELER-DUELLE --------------------



def neuer_raumcode():

    for _ in range(100):

        code = str(random.randint(100000, 999999))

        if code not in DUELLE:

            return code

    return uuid.uuid4().hex[:6].upper()





def duell_aufräumen():

    """Alte Räume nach 6 Stunden entfernen."""

    grenze = time.time() - 6 * 60 * 60

    for code in list(DUELLE):

        if DUELLE[code].get("erstellt", 0) < grenze:

            DUELLE.pop(code, None)





def rangliste(raum):

    return sorted(

        [

            {"name": s["name"], "punkte": s["punkte"], "rang": s.get("rang", "🌱 Anfänger")}

            for s in raum["spieler"].values()

        ],

        key=lambda s: (-s["punkte"], s["name"].lower())

    )





FRAGE_ZEIT = 20





def naechste_frage_oder_ende(raum):

    if raum["frage_index"] + 1 >= len(raum["fragen"]):

        raum["status"] = "fertig"

        raum["frage_start"] = None

    else:

        raum["frage_index"] += 1

        raum["antworten"] = set()

        raum["frage_start"] = time.time()





def timer_pruefen(raum):

    if raum["status"] != "laeuft" or not raum.get("frage_start"):

        return

    if time.time() - raum["frage_start"] >= FRAGE_ZEIT:

        naechste_frage_oder_ende(raum)





def raum_ansicht(raum, spieler_id=None):

    timer_pruefen(raum)

    index = raum["frage_index"]

    status = raum["status"]

    frage_text = ""



    if status == "laeuft" and 0 <= index < len(raum["fragen"]):

        frage_text = raum["fragen"][index].get("frage", "")



    return {

        "code": raum["code"],

        "titel": raum["titel"],

        "status": status,

        "frage_index": index,

        "fragen_anzahl": len(raum["fragen"]),

        "frage": frage_text,

        "zeit_limit": FRAGE_ZEIT,

        "zeit_uebrig": (

            max(0, int(FRAGE_ZEIT - (time.time() - raum["frage_start"]) + 0.999))

            if status == "laeuft" and raum.get("frage_start")

            else 0

        ),

        "spieler": [

            {"name": s["name"], "punkte": s["punkte"], "rang": s.get("rang", "🌱 Anfänger")}

            for s in raum["spieler"].values()

        ],

        "rangliste": rangliste(raum),

        "hat_geantwortet": (

            spieler_id in raum["antworten"]

            if spieler_id else False

        )

    }





@app.route("/duelle", methods=["POST"])

def duell_erstellen_route():

    daten = request.get_json(silent=True) or {}

    fragen = daten.get("fragen", [])



    if not isinstance(fragen, list) or not fragen:

        return jsonify({"fehler": "Das Quiz braucht mindestens eine Frage."}), 400



    with DUELL_LOCK:

        duell_aufräumen()

        code = neuer_raumcode()

        host_token = uuid.uuid4().hex

        raum = {

            "code": code,

            "host_token": host_token,

            "titel": str(daten.get("titel", "Quiz-Duell")),

            "fragen": fragen,

            "status": "warten",

            "frage_index": -1,

            "spieler": {},

            "antworten": set(),

            "frage_start": None,

            "erstellt": time.time()

        }

        DUELLE[code] = raum

        ansicht = raum_ansicht(raum)

        ansicht["host_token"] = host_token

        return jsonify(ansicht), 201





@app.route("/duelle/<code>/beitreten", methods=["POST"])

def duell_beitreten_route(code):

    daten = request.get_json(silent=True) or {}

    name = str(daten.get("name", "")).strip()[:30]



    if not name:

        return jsonify({"fehler": "Bitte einen Namen eingeben."}), 400



    with DUELL_LOCK:

        raum = DUELLE.get(str(code))

        if not raum:

            return jsonify({"fehler": "Raumcode nicht gefunden."}), 404

        if raum["status"] != "warten":

            return jsonify({"fehler": "Dieses Duell wurde bereits gestartet."}), 409



        spieler_id = uuid.uuid4().hex

        raum["spieler"][spieler_id] = {
            "name": name,
            "punkte": 0,
            "rang": rang_fuer_xp(daten.get("xp", 0)),
            "sprache": str(daten.get("sprache", "de"))[:8]
        }



        ansicht = raum_ansicht(raum, spieler_id)

        ansicht["spieler_id"] = spieler_id

        return jsonify(ansicht), 201





@app.route("/duelle/<code>", methods=["GET"])

def duell_status_route(code):

    spieler_id = request.args.get("spieler_id")

    with DUELL_LOCK:

        raum = DUELLE.get(str(code))

        if not raum:

            return jsonify({"fehler": "Raumcode nicht gefunden."}), 404

        return jsonify(raum_ansicht(raum, spieler_id))





@app.route("/duelle/<code>/start", methods=["POST"])

def duell_start_route(code):

    daten = request.get_json(silent=True) or {}



    with DUELL_LOCK:

        raum = DUELLE.get(str(code))

        if not raum:

            return jsonify({"fehler": "Raumcode nicht gefunden."}), 404

        if daten.get("host_token") != raum["host_token"]:

            return jsonify({"fehler": "Nur der Host darf das Duell starten."}), 403

        if not raum["spieler"]:

            return jsonify({"fehler": "Mindestens ein Mitspieler muss beitreten."}), 400



        raum["status"] = "laeuft"

        raum["frage_index"] = 0

        raum["antworten"] = set()

        raum["frage_start"] = time.time()

        return jsonify(raum_ansicht(raum))





@app.route("/duelle/<code>/antwort", methods=["POST"])

def duell_antwort_route(code):

    daten = request.get_json(silent=True) or {}

    spieler_id = daten.get("spieler_id")

    antwort = str(daten.get("antwort", "")).strip()



    with DUELL_LOCK:

        raum = DUELLE.get(str(code))

        if not raum:

            return jsonify({"fehler": "Raumcode nicht gefunden."}), 404

        if raum["status"] != "laeuft":

            return jsonify({"fehler": "Das Duell läuft gerade nicht."}), 409

        if spieler_id not in raum["spieler"]:

            return jsonify({"fehler": "Spieler nicht gefunden."}), 404

        if spieler_id in raum["antworten"]:

            return jsonify({"fehler": "Für diese Frage wurde bereits geantwortet."}), 409



        index = raum["frage_index"]

        if index < 0 or index >= len(raum["fragen"]):

            return jsonify({"fehler": "Keine aktive Frage."}), 409



        richtig = str(raum["fragen"][index].get("antwort", "")).strip()

        ist_richtig = antwort.casefold() == richtig.casefold()



        if ist_richtig:

            raum["spieler"][spieler_id]["punkte"] += 1



        raum["antworten"].add(spieler_id)



        # Sobald alle geantwortet haben, geht es sofort weiter.

        # Sonst übernimmt der 20-Sekunden-Timer den Wechsel.

        if len(raum["antworten"]) >= len(raum["spieler"]):

            naechste_frage_oder_ende(raum)



        ansicht = raum_ansicht(raum, spieler_id)

        ansicht["richtig"] = ist_richtig

        return jsonify(ansicht)





if __name__ == "__main__":

    app.run(host="0.0.0.0", port=5001, debug=False)



# --- Sichere Mini-Community: nur fest vorgegebene Nachrichten, kein Freitext ---
COMMUNITY_MESSAGES = []
COMMUNITY_LOCK = threading.Lock()
COMMUNITY_RATE = {}
COMMUNITY_ALLOWED = {"GG", "QUIZ", "HARD", "LEARN", "AGAIN", "NICE"}

@app.route("/community", methods=["GET"])
def community_laden():
    with COMMUNITY_LOCK:
        return jsonify(list(COMMUNITY_MESSAGES[-100:]))

@app.route("/community", methods=["POST"])
def community_senden():
    data = request.get_json(silent=True) or {}
    key = str(data.get("message", "")).strip().upper()
    name = str(data.get("name", "User")).strip()
    if key not in COMMUNITY_ALLOWED:
        return jsonify({"fehler": "Nur vorgegebene Community-Nachrichten sind erlaubt."}), 400
    if not (1 <= len(name) <= 24) or any(ord(c) < 32 for c in name):
        return jsonify({"fehler": "Ungültiger Name."}), 400
    # Kleines Rate-Limit: höchstens eine Nachricht alle 3 Sekunden pro IP.
    now = time.time()
    ident = request.remote_addr or "unknown"
    with COMMUNITY_LOCK:
        last = COMMUNITY_RATE.get(ident, 0)
        if now - last < 3:
            return jsonify({"fehler": "Bitte kurz warten."}), 429
        COMMUNITY_RATE[ident] = now
        COMMUNITY_MESSAGES.append({"id": uuid.uuid4().hex[:12], "name": name, "message": key, "time": int(now)})
        del COMMUNITY_MESSAGES[:-100]
    return jsonify({"ok": True}), 201
