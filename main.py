from flask import Flask, render_template, request, send_from_directory, Response
from deepface import DeepFace
import os
import wikipedia
from werkzeug.exceptions import RequestEntityTooLarge
import logging
import json
from datetime import datetime
from werkzeug.utils import secure_filename
from queue import Queue

# ------------------ CONFIG ------------------

progress_queue = Queue()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

base_dir = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(base_dir, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "bmp"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ------------------ HELPERS ------------------

def log_progress(message):
    """Log progress messages to the queue"""
    progress_queue.put(message)
    logger.info(message)

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def cleanup_files(*paths):
    """Delete uploaded files to prevent folder bloat"""
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                log_progress("🧹 Cleaning up temporary files")
        except Exception as e:
            logger.error(f"Error deleting {path}: {e}")

def has_face(path: str) -> bool:
    """Check if an image contains at least one face with confidence >= 0.90"""
    try:
        faces = DeepFace.extract_faces(
            img_path=path,
            detector_backend="retinaface",
            enforce_detection=False
        )
        if not faces:
            return False

        for f in faces:
            conf = float(f.get("confidence", 0.0))
            log_progress(f"👤 Face detected (confidence: {conf:.2f})")

            if conf >= 0.90:
                return True

        return False
    except Exception as e:
        logger.error(f"Face detection error for {path}: {e}")
        return False

def get_wiki_summary(name: str) -> str:
    """Fetch a short Wikipedia summary for a given filename"""
    try:
        base = os.path.splitext(os.path.basename(name))[0]
        query = base.replace("_", " ").replace("-", " ").strip()
        if not query:
            return ""

        wikipedia.set_lang("en")
        candidates = wikipedia.search(query)
        if not candidates:
            return f"No Wikipedia match found for “{query}”."

        for title in candidates[:5]:
            try:
                summary = wikipedia.summary(
                    title, sentences=2, auto_suggest=False, redirect=True
                ).replace("\n", " ").strip()
            except Exception:
                continue

            text = summary.lower()
            if "may refer to" in text or "given name" in text or "surname" in text:
                continue

            return summary

        return f"No suitable biography found for “{query}”."

    except Exception as e:
        logger.error(f"Wikipedia error: {e}")
        return ""

def add_to_history(p1_name, p2_name, distance, verified):
    """Log comparison to history.json"""
    history_file = os.path.join(base_dir, "history.json")
    
    entry = {
        "timestamp": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "person1": p1_name,
        "person2": p2_name,
        "distance": round(distance, 4),
        "verified": verified
    }

    try:
        # 1. Load existing history
        if os.path.exists(history_file):
            with open(history_file, "r", encoding="utf-8") as f:
                try:
                    history = json.load(f)
                except json.JSONDecodeError:
                    history = []
        else:
            history = []

        # 2. Add the new entry at the top
        history.insert(0, entry)

        # 3. Limit to the last 100 entries
        history = history[:100]

        # 4. Save back to file
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)

        log_progress("📝 Comparison saved to history")

    except Exception as e:
        logger.error(f"Error updating history.json: {e}")

# ------------------ ROUTES ------------------

@app.route("/progress")
def progress():
    """Stream progress updates to the client."""
    def generate():
        while True:
            message = progress_queue.get()
            yield f"data: {message}\n\n"
            if message == "__DONE__":
                break
    return Response(generate(), mimetype="text/event-stream")

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route("/", methods=["GET", "POST"])
def index():
    history_file = os.path.join(base_dir, "history.json")
    recent_history = []
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding = "utf-8") as f:
                recent_history = json.load(f)[:5]
        except Exception as e:
            logger.error(f"Error loading recent history: {e}")


    if request.method == "GET":
        return render_template("index.html", history=recent_history)

    # ---- get uploaded files ----
    file1 = request.files.get("image1")
    file2 = request.files.get("image2")

    if not file1 or not file2:
        return render_template("index.html", error="Both images are required.")

    filename1 = secure_filename(file1.filename)
    filename2 = secure_filename(file2.filename)

    if filename1 == "" or filename2 == "":
        return render_template("index.html", error="No files selected.")

    if not allowed_file(filename1) or not allowed_file(filename2):
        return render_template("index.html", error="Invalid file type.")

    p1 = os.path.join(UPLOAD_FOLDER, filename1)
    p2 = os.path.join(UPLOAD_FOLDER, filename2)

    # ---- save files ----
    try:
        file1.save(p1)
        file2.save(p2)
        log_progress("📂 Images uploaded and saved")
    except Exception as e:
        cleanup_files(p1, p2)
        return render_template("index.html", error=f"Error saving files: {e}")

    # ---- face detection ----
    if not has_face(p1):
        cleanup_files(p1, p2)
        return render_template("index.html", error="No face detected in the first image.")

    if not has_face(p2):
        cleanup_files(p1, p2)
        return render_template("index.html", error="No face detected in the second image.")

    # ---- face verification ----
    log_progress("🧠 Running DeepFace comparison...")

    try:
        result = DeepFace.verify(
            img1_path=p1,
            img2_path=p2,
            detector_backend="retinaface",
            model_name="ArcFace",
            distance_metric="cosine",
            enforce_detection=True
        )
    except Exception as e:
        cleanup_files(p1, p2)
        logger.error(f"Face verification error: {e}")
        return render_template("index.html", error="Face verification failed.")

    distance = float(result.get("distance", 1.0))
    threshold = float(result.get("threshold", 0.4))
    similarity_pct = max(0.0, min(100.0, (1.0 - distance) * 100.0))

    if distance <= threshold * 0.90:
        tier, emoji = "similar", "🟩"
    elif distance <= threshold * 1.25:
        tier, emoji = "middle", "🟪"
    else:
        tier, emoji = "different", "🟥"

    person1_name = os.path.splitext(filename1)[0].replace("_", " ").title()
    person2_name = os.path.splitext(filename2)[0].replace("_", " ").title()

    add_to_history(person1_name, person2_name, distance, result.get("verified", False))
    log_progress("__DONE__")  # 🔹 important fix

    # ---- render result ----
    if result.get("verified"):
        info = get_wiki_summary(person1_name)
        return render_template(
            "result.html",
            verified=True,
            distance=distance,
            similarity_pct=similarity_pct,
            tier=tier,
            emoji=emoji,
            file=filename1,
            info=info,
            person_name=person1_name
        )
    else:
        info1 = get_wiki_summary(person1_name)
        info2 = get_wiki_summary(person2_name)
        return render_template(
            "result.html",
            verified=False,
            distance=distance,
            similarity_pct=similarity_pct,
            tier=tier,
            emoji=emoji,
            file1=filename1,
            file2=filename2,
            info1=info1,
            info2=info2,
            person1_name=person1_name,
            person2_name=person2_name
        )


@app.route("/history")
def history():
    history_file = os.path.join(base_dir, "history.json")
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        except json.JSONDecodeError:
            history = []
    else:
        history = []

    return render_template("history.html", history=history)


# ------------------ RUN ------------------
if __name__ == "__main__":
    app.run(debug=True, port=5002)

# ./.venv/bin/python main.py