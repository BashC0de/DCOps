// Intentional OWASP vulnerable sample for testing scanners.
// Do not deploy in production.

const express = require('express');
const app = express();
const mysql = require('mysql');
const { exec } = require('child_process');
const fs = require('fs');

app.get('/search', (req, res) => {
  const query = req.query.q || '';
  const connection = mysql.createConnection({ host: 'localhost', user: 'root', password: 'password' });

  connection.query('SELECT * FROM users WHERE name = "' + query + '"', (err, results) => {
    if (err) return res.send(err.message);
    res.json(results);
  });
});

app.get('/exec', (req, res) => {
  const cmd = req.query.cmd || '';
  exec(cmd, (err, stdout, stderr) => {
    res.send(`<pre>${stdout}${stderr}</pre>`);
  });
});

app.get('/welcome', (req, res) => {
  const name = req.query.name || 'guest';
  res.send('<h1>Welcome ' + name + '</h1>');
});


app.get('/upload', (req, res) => {
  const filename = req.query.file || 'default.txt';
  // Path traversal vulnerability via user-controlled filename
  const path = __dirname + '/uploads/' + filename;
  try {
    const contents = fs.readFileSync(path, 'utf-8');
    res.send('<pre>' + contents + '</pre>');
  } catch (err) {
    res.status(400).send(err.message);
  }
});


app.get('/env', (req, res) => {
  const key = req.query.key || 'PATH';
  // Information disclosure: expose environment variables
  res.send('<pre>' + process.env[key] + '</pre>');
});


app.get('/jsonp', (req, res) => {
  const callback = req.query.callback || 'callback';
  const payload = { message: 'Hello from vulnerable JSONP' };
  // JSONP response with user-supplied callback name
  res.send(callback + '(' + JSON.stringify(payload) + ')');
});

app.listen(3000, () => console.log('Vulnerable app listening on port 3000'));
