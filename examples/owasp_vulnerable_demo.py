"""
INTENTIONAL OWASP vulnerable sample for security scanning and training.
Do not deploy this in production. Use only for testing SAST/DAST tools.
"""

import hashlib
import os
import sqlite3
import subprocess
from flask import Flask, Response, request

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


if __name__ == "__main__":
    app.run(debug=True)
