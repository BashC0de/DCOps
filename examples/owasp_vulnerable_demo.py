"""
INTENTIONAL OWASP vulnerable sample for security scanning and training.
Do not deploy this in production. Use only for testing SAST/DAST tools.
"""

import base64
import hashlib
import os
import pickle
import sqlite3
import subprocess
from flask import Flask, Response, request, redirect

app = Flask(__name__)

# Hardcoded secret / credential
API_KEY = "sk-live-1234567890abcdefghijklmnop"


def get_user_by_username(username: str):
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE users (username TEXT, password TEXT)")
    cursor.execute("INSERT INTO users VALUES ('admin', 'password123')")

    # SQL injection: unsanitized input is concatenated into the SQL string
    query = f"SELECT * FROM users WHERE username = '{username}'"
    cursor.execute(query)
    return cursor.fetchall()


@app.route("/login")
def login():
    username = request.args.get("username", "")
    password = request.args.get("password", "")
    user = get_user_by_username(username)
    return {"user": user, "password": password}


@app.route("/run")
def run_command():
    cmd = request.args.get("cmd", "")

    # Command injection: shell=True allows arbitrary command execution
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return {"stdout": result.stdout, "stderr": result.stderr}


@app.route("/download")
def download_file():
    filename = request.args.get("file", "")

    # Path traversal: user-controlled file path is joined with a base directory
    path = os.path.join("/tmp", filename)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


@app.route("/welcome")
def welcome():
    name = request.args.get("name", "guest")

    # Reflected XSS: raw user input is embedded into HTML without encoding
    return Response(f"<h1>Welcome {name}</h1>", mimetype="text/html")


@app.route("/hash")
def hash_password():
    password = request.args.get("password", "")

    # Weak hashing: MD5 is insecure for password storage
    return {"md5": hashlib.md5(password.encode("utf-8")).hexdigest()}


@app.route("/deserialize")
def deserialize():
    payload = request.args.get("data", "")
    # Insecure deserialization: untrusted pickle data can execute arbitrary code
    try:
        obj = pickle.loads(base64.b64decode(payload))
    except Exception as exc:
        return {"error": str(exc)}, 400
    return {"object": repr(obj)}


@app.route("/redirect")
def open_redirect():
    url = request.args.get("url", "")
    # Open redirect: trust user-controlled URL without validation
    return redirect(url or "/")


@app.route("/eval")
def unsafe_eval():
    code = request.args.get("code", "")
    # Code injection: evaluating untrusted input is dangerous
    try:
        result = eval(code)
    except Exception as exc:
        return {"error": str(exc)}, 400
    return {"result": str(result)}


if __name__ == "__main__":
    app.run(debug=True)
