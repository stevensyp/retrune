import os

from flask import Flask, jsonify, render_template, request, send_file

from export_engine import JobStore, ResolveError, resolve_input


app = Flask(__name__)

ROOT_DIR = os.path.dirname(__file__)
DOWNLOAD_DIR = os.path.join(ROOT_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

job_store = JobStore(DOWNLOAD_DIR)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/capabilities")
def capabilities():
    return jsonify(job_store.capabilities())


@app.route("/api/resolve", methods=["POST"])
def resolve():
    data = request.get_json(silent=True) or {}
    raw_input = data.get("input") or data.get("url") or ""
    try:
        return jsonify(resolve_input(raw_input))
    except ResolveError as err:
        return jsonify({"error": str(err)}), 400


@app.route("/api/jobs", methods=["POST"])
def create_job():
    data = request.get_json(silent=True) or {}
    try:
        job = job_store.create(data)
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    return jsonify({"job_id": job["id"], "status": job["status"]})


@app.route("/api/jobs/<job_id>")
def read_job(job_id):
    job = job_store.public(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/api/jobs/<job_id>/artifacts/<artifact_id>")
def download_artifact(job_id, artifact_id):
    artifact = job_store.artifact(job_id, artifact_id)
    if not artifact:
        return jsonify({"error": "Artifact not found"}), 404
    return send_file(
        artifact["path"],
        as_attachment=True,
        download_name=artifact["filename"],
    )


@app.route("/api/jobs/<job_id>/zip")
def download_zip(job_id):
    zip_path = job_store.zip_path(job_id)
    if not zip_path:
        return jsonify({"error": "ZIP not ready"}), 404
    return send_file(zip_path, as_attachment=True, download_name=f"reclip-{job_id}.zip")


# Compatibility wrappers for the original ReClip frontend/API shape.
@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    try:
        resolved = resolve_input(url)
    except ResolveError as err:
        return jsonify({"error": str(err)}), 400
    if not resolved["items"]:
        return jsonify({"error": "No media found"}), 400
    item = resolved["items"][0]
    return jsonify(
        {
            "title": item.get("title", ""),
            "thumbnail": item.get("thumbnail", ""),
            "duration": item.get("duration"),
            "uploader": item.get("uploader", ""),
            "formats": item.get("formats", []),
        }
    )


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    job = job_store.create(
        {
            "input": url,
            "output_format": "audio" if data.get("format") == "audio" else "video",
            "quick_format_id": data.get("format_id"),
            "mode": "quick",
            "title": data.get("title", ""),
        }
    )
    return jsonify({"job_id": job["id"]})


@app.route("/api/status/<job_id>")
def check_status(job_id):
    job = job_store.public(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    first_artifact = next(iter(job.get("artifacts", [])), {})
    status = job["status"]
    if status == "partial":
        status = "done"
    return jsonify(
        {
            "status": status,
            "error": job.get("error"),
            "filename": first_artifact.get("filename"),
        }
    )


@app.route("/api/file/<job_id>")
def download_file(job_id):
    job = job_store.public(job_id)
    if not job or job["status"] not in {"done", "partial"} or not job.get("artifacts"):
        return jsonify({"error": "File not ready"}), 404
    artifact_id = job["artifacts"][0]["id"]
    artifact = job_store.artifact(job_id, artifact_id)
    return send_file(
        artifact["path"],
        as_attachment=True,
        download_name=artifact["filename"],
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8899))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port)
