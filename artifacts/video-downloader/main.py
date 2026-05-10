import os
import json
import uuid
import threading
import time
from flask import Flask, render_template, request, jsonify, send_file

import yt_dlp

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

tasks = {}


def cleanup_old_files():
    now = time.time()
    for filename in os.listdir(DOWNLOAD_DIR):
        filepath = os.path.join(DOWNLOAD_DIR, filename)
        if os.path.isfile(filepath) and now - os.path.getmtime(filepath) > 3600:
            try:
                os.remove(filepath)
            except OSError:
                pass


def fetch_video_info(task_id, url):
    try:
        tasks[task_id]["status"] = "fetching"

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        if info.get("formats"):
            seen = set()
            for f in info["formats"]:
                ext = f.get("ext", "mp4")
                height = f.get("height")
                filesize = f.get("filesize") or f.get("filesize_approx")
                format_id = f.get("format_id", "")
                vcodec = f.get("vcodec", "none")
                acodec = f.get("acodec", "none")

                if vcodec == "none" or height is None:
                    continue

                label = f"{height}p"
                if label in seen:
                    continue
                seen.add(label)

                formats.append(
                    {
                        "format_id": format_id,
                        "ext": ext,
                        "quality": label,
                        "height": height,
                        "filesize": filesize,
                    }
                )

            formats.sort(key=lambda x: x.get("height", 0), reverse=True)

        if not formats:
            formats = [
                {
                    "format_id": "best",
                    "ext": "mp4",
                    "quality": "Best",
                    "height": 0,
                    "filesize": None,
                }
            ]

        tasks[task_id]["status"] = "ready"
        tasks[task_id]["info"] = {
            "title": info.get("title", "Unknown"),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader", "Unknown"),
            "formats": formats,
        }

    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["error"] = str(e)


def download_video(task_id, url, format_id):
    try:
        tasks[task_id]["status"] = "downloading"
        cleanup_old_files()

        file_id = str(uuid.uuid4())[:8]
        output_template = os.path.join(DOWNLOAD_DIR, f"{file_id}_%(title)s.%(ext)s")

        ydl_opts = {
            "format": f"{format_id}+bestaudio/best" if format_id != "best" else "best",
            "outtmpl": output_template,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "merge_output_format": "mp4",
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if not os.path.exists(filename):
                base, _ = os.path.splitext(filename)
                filename = base + ".mp4"

        tasks[task_id]["status"] = "complete"
        tasks[task_id]["filename"] = os.path.basename(filename)

    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["error"] = str(e)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/fetch", methods=["POST"])
def fetch_info():
    data = request.get_json()
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "Please provide a URL"}), 400

    task_id = str(uuid.uuid4())[:8]
    tasks[task_id] = {"status": "started", "url": url}

    thread = threading.Thread(target=fetch_video_info, args=(task_id, url))
    thread.daemon = True
    thread.start()

    return jsonify({"task_id": task_id})


@app.route("/download", methods=["POST"])
def start_download():
    data = request.get_json()
    url = data.get("url", "").strip()
    format_id = data.get("format_id", "best")

    if not url:
        return jsonify({"error": "Please provide a URL"}), 400

    task_id = str(uuid.uuid4())[:8]
    tasks[task_id] = {"status": "started", "url": url}

    thread = threading.Thread(target=download_video, args=(task_id, url, format_id))
    thread.daemon = True
    thread.start()

    return jsonify({"task_id": task_id})


@app.route("/status/<task_id>")
def check_status(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task)


@app.route("/file/<filename>")
def serve_file(filename):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    return send_file(filepath, as_attachment=True)


if __name__ == "__main__":
    import sys

    port = int(os.environ.get("PORT", 5000))
    print(f"Starting server on port {port}", flush=True)
    sys.stdout.flush()
    app.run(host="0.0.0.0", port=port, debug=False)
