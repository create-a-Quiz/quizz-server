from flask import Flask, request, jsonify
import json
import os
import uuid

app = Flask(__name__)

SKRIPT_ORDNER = os.path.dirname(os.path.abspath(__file__))
DATEINAME = os.path.join(SKRIPT_ORDNER, "server_quizze.json")


def quizze_laden():
    if os.path.exists(DATEINAME):
        with open(DATEINAME, "r", encoding="utf-8") as datei:
            return json.load(datei)
    return []


def quizze_speichern(quizze):
    with open(DATEINAME, "w", encoding="utf-8") as datei:
        json.dump(quizze, datei, ensure_ascii=False, indent=2)


@app.route("/quizze", methods=["GET"])
def alle_quizze_abrufen():
    """Gibt alle öffentlichen Quizze zurück (ohne die Antworten zu verraten wäre später sinnvoll)."""
    quizze = quizze_laden()
    return jsonify(quizze)


@app.route("/quizze/<quiz_id>", methods=["GET"])
def ein_quiz_abrufen(quiz_id):
    """Gibt ein einzelnes Quiz anhand seiner ID zurück."""
    quizze = quizze_laden()
    for quiz in quizze:
        if quiz["id"] == quiz_id:
            return jsonify(quiz)
    return jsonify({"fehler": "Quiz nicht gefunden"}), 404


@app.route("/quizze", methods=["POST"])
def quiz_veroeffentlichen():
    """Nimmt ein neues Quiz entgegen und speichert es auf dem Server."""
    daten = request.get_json()

    if not daten or "titel" not in daten or "fragen" not in daten:
        return jsonify({"fehler": "Titel und Fragen sind erforderlich"}), 400

    quizze = quizze_laden()

    neues_quiz = {
        "id": uuid.uuid4().hex[:8],
        "titel": daten["titel"],
        "fragen": daten["fragen"]
    }
    quizze.append(neues_quiz)
    quizze_speichern(quizze)

    return jsonify(neues_quiz), 201


if __name__ == "__main__":
    # host="0.0.0.0" macht den Server auch von anderen Geräten im selben WLAN erreichbar
    # Port 5001 statt 5000, da 5000 auf dem Mac oft vom AirPlay-Empfänger belegt ist
    # debug=False, damit der Server als Hintergrundprozess laufen kann
    # (der Debug-Modus schreibt eine Sicherheits-PIN direkt ans Terminal,
    # was Hintergrundprozesse pausiert)
    app.run(host="0.0.0.0", port=5001, debug=False)