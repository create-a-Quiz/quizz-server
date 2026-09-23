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


def quiz_finden(quizze, quiz_id):
    for quiz in quizze:
        if str(quiz.get("id")) == str(quiz_id):
            return quiz
    return None


def oeffentliche_ansicht(quiz):
    """
    Gibt eine Kopie des Quiz zurück, OHNE den owner_token - der bleibt
    geheim auf dem Server, damit andere Nutzer ihn nicht sehen und sich
    nicht als Besitzer ausgeben können.
    """
    return {
        "id": quiz.get("id"),
        "titel": quiz.get("titel"),
        "fragen": quiz.get("fragen", [])
    }


@app.route("/quizze", methods=["GET"])
def alle_quizze_abrufen():
    """Gibt alle öffentlichen Quizze zurück (ohne Besitzer-Token)."""
    quizze = quizze_laden()
    return jsonify([oeffentliche_ansicht(q) for q in quizze])


@app.route("/quizze/<quiz_id>", methods=["GET"])
def ein_quiz_abrufen(quiz_id):
    """Gibt ein einzelnes Quiz anhand seiner ID zurück (ohne Besitzer-Token)."""
    quizze = quizze_laden()
    quiz = quiz_finden(quizze, quiz_id)
    if quiz:
        return jsonify(oeffentliche_ansicht(quiz))
    return jsonify({"fehler": "Quiz nicht gefunden"}), 404


@app.route("/quizze", methods=["POST"])
def quiz_veroeffentlichen():
    """Nimmt ein neues Quiz entgegen und speichert es auf dem Server."""
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
    """Aktualisiert ein bestehendes Quiz - nur der ursprüngliche Ersteller darf das."""
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
    """Löscht ein Quiz - nur der ursprüngliche Ersteller darf das."""
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
