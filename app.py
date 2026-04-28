import os
import hashlib
import hmac
import secrets
import time
from datetime import timedelta

from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for

from export_engine import JobStore, ResolveError, resolve_input


app = Flask(__name__)

ROOT_DIR = os.path.dirname(__file__)
DOWNLOAD_DIR = os.path.join(ROOT_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

job_store = JobStore(DOWNLOAD_DIR)
DEV_RELOAD = os.environ.get("RECLIP_DEV_RELOAD") == "1"
AUTH_PASSWORD = os.environ.get("RECLIP_PASSWORD", "")
AUTH_PASSWORD_SHA256 = os.environ.get("RECLIP_PASSWORD_SHA256", "").lower()
AUTH_REQUIRED = os.environ.get("RECLIP_AUTH_REQUIRED") == "1"
AUTH_ENABLED = bool(AUTH_PASSWORD or AUTH_PASSWORD_SHA256)
AUTH_FAILURES = {}
SECRET_KEY = os.environ.get("SECRET_KEY")
SESSION_HOURS = int(os.environ.get("RECLIP_SESSION_HOURS", "720"))

if AUTH_REQUIRED and not AUTH_ENABLED:
    raise RuntimeError("RECLIP_AUTH_REQUIRED=1 but no RECLIP_PASSWORD or RECLIP_PASSWORD_SHA256 is set")
if AUTH_REQUIRED and not SECRET_KEY:
    raise RuntimeError("RECLIP_AUTH_REQUIRED=1 but no SECRET_KEY is set")

if AUTH_ENABLED:
    app.secret_key = SECRET_KEY or secrets.token_hex(32)
    app.config.update(
        PERMANENT_SESSION_LIFETIME=timedelta(hours=SESSION_HOURS),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("RECLIP_COOKIE_SECURE") == "1",
    )


def _client_ip():
    forwarded = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.remote_addr or "unknown"


def _password_matches(password):
    if AUTH_PASSWORD_SHA256:
        digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(digest, AUTH_PASSWORD_SHA256)
    return hmac.compare_digest(password, AUTH_PASSWORD)


def _auth_failure_state(ip):
    state = AUTH_FAILURES.get(ip)
    if not state:
        return {"count": 0, "locked_until": 0}
    if state.get("locked_until", 0) <= time.time() and state.get("count", 0) > 40:
        state = {"count": 0, "locked_until": 0}
        AUTH_FAILURES[ip] = state
    return state


def _register_auth_failure(ip):
    now = time.time()
    state = _auth_failure_state(ip)
    count = state.get("count", 0) + 1
    locked_until = state.get("locked_until", 0)
    if count >= 5:
        lock_seconds = min(3600, 60 * (2 ** min(count - 5, 6)))
        locked_until = now + lock_seconds
    AUTH_FAILURES[ip] = {"count": count, "locked_until": locked_until}
    return max(0, int(locked_until - now))


def _clear_auth_failures(ip):
    AUTH_FAILURES.pop(ip, None)


def _auth_locked_seconds(ip):
    state = _auth_failure_state(ip)
    remaining = int(state.get("locked_until", 0) - time.time())
    return max(0, remaining)


@app.before_request
def require_auth():
    if not AUTH_ENABLED:
        return None
    if request.endpoint in {"login", "health", "static"}:
        return None
    if session.get("authenticated"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "Authentication required"}), 401
    return redirect(url_for("login"))


@app.route("/auth/login", methods=["GET", "POST"])
def login():
    if not AUTH_ENABLED:
        return redirect(url_for("index"))

    ip = _client_ip()
    locked_seconds = _auth_locked_seconds(ip)
    error = ""

    if request.method == "POST":
        csrf_token = request.form.get("csrf_token", "")
        expected_token = session.get("csrf_token", "")
        if not expected_token or not hmac.compare_digest(csrf_token, expected_token):
            error = "Session expired. Reload and try again."
        elif locked_seconds > 0:
            error = f"Too many attempts. Try again in {locked_seconds} seconds."
        elif _password_matches(request.form.get("password", "")):
            session.clear()
            session.permanent = True
            session["authenticated"] = True
            _clear_auth_failures(ip)
            return redirect(url_for("index"))
        else:
            locked_seconds = _register_auth_failure(ip)
            error = "Password not accepted."
            if locked_seconds > 0:
                error = f"Too many attempts. Try again in {locked_seconds} seconds."

    csrf_token = secrets.token_urlsafe(32)
    session["csrf_token"] = csrf_token
    return render_template(
        "login.html",
        csrf_token=csrf_token,
        error=error,
        locked_seconds=locked_seconds,
    )


@app.route("/health")
def health():
    return jsonify({"ok": True})


def _dev_reload_version():
    watch_paths = [__file__, os.path.join(ROOT_DIR, "export_engine.py")]
    for folder in ("templates", "static"):
        root = os.path.join(ROOT_DIR, folder)
        for dirpath, _, filenames in os.walk(root):
            for filename in filenames:
                if os.path.splitext(filename)[1] in {".html", ".css", ".js", ".svg"}:
                    watch_paths.append(os.path.join(dirpath, filename))

    parts = []
    for path in sorted(watch_paths):
        try:
            stat = os.stat(path)
        except OSError:
            continue
        parts.append(f"{os.path.relpath(path, ROOT_DIR)}:{stat.st_mtime_ns}:{stat.st_size}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


@app.route("/")
def index():
    return render_template("index.html", dev_reload=DEV_RELOAD)


@app.route("/api/dev/reload-version")
def dev_reload_version():
    if not DEV_RELOAD:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"version": _dev_reload_version()})


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
    app.run(host=host, port=port, debug=DEV_RELOAD, use_reloader=DEV_RELOAD)
