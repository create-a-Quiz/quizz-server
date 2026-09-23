from flask import Flask, request, jsonify
import json
import os
import uuid
import random
import threading
import time

app = Flask(__name__)

SKRIPT_ORDNER = os.path.dirname(os.path.abspath(__file__))
DATEINAME = os.path.join(SKRIPT_ORDNER, "server_quizze.json")

# Duellräume liegen absichtlich nur im Arbeitsspeicher.
# Bei einem Server-Neustart verschwinden laufende Räume.
DUELLE = {}
DUELL_LOCK = threading.Lock()


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


def oeffentliche_ansicht(quiz):
    return {
        "id": quiz.get("id"),
        "titel": quiz.get("titel"),
        "fragen": quiz.get("fragen", [])
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

    quizze = quizze_laden()
    neues_quiz = {
        "id": uuid.uuid4().hex[:8],
        "titel": daten["titel"],
        "fragen": daten["fragen"],
        "owner_token": daten.get("owner_token", "")
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
    if quiz.get("owner_token") != daten.get("owner_token"):
        return jsonify({"fehler": "Keine Berechtigung für dieses Quiz"}), 403

    if "titel" in daten:
        quiz["titel"] = daten["titel"]
    if "fragen" in daten:
        quiz["fragen"] = daten["fragen"]

    quizze_speichern(quizze)
    return jsonify(oeffentliche_ansicht(quiz))


@app.route("/quizze/<quiz_id>", methods=["DELETE"])
def quiz_loeschen(quiz_id):
    daten = request.get_json(silent=True) or {}
    quizze = quizze_laden()
    quiz = quiz_finden(quizze, quiz_id)

    if not quiz:
        return jsonify({"fehler": "Quiz nicht gefunden"}), 404
    if quiz.get("owner_token") != daten.get("owner_token"):
        return jsonify({"fehler": "Keine Berechtigung für dieses Quiz"}), 403

    quizze = [q for q in quizze if str(q.get("id")) != str(quiz_id)]
    quizze_speichern(quizze)
    return jsonify({"erfolg": True})


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
            {"name": s["name"], "punkte": s["punkte"]}
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
            {"name": s["name"], "punkte": s["punkte"]}
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
            "punkte": 0
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
