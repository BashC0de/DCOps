OWASP Vulnerable Demo

This folder contains intentionally vulnerable examples for local scanning only. Do NOT deploy these files.

Files:
- owasp_vulnerable_demo.py: Flask app with multiple vulnerabilities
- owasp_vulnerable_demo.js: Node/Express app with vulnerabilities
- vulnerable_page.html: simple reflected XSS demo
- seed_vuln.sql: SQL seed with plain passwords

Quick run (Python demo):

1. Activate your virtualenv and install dependencies:

   python -m pip install flask

2. Run the Flask demo:

   python examples/owasp_vulnerable_demo.py

Quick run (Node demo):

1. Install dependencies:

   npm install express mysql

2. Run the Node demo:

   node examples/owasp_vulnerable_demo.js

Open `examples/vulnerable_page.html` in a browser and try `?q=<script>alert(1)</script>` to test reflected XSS locally.
