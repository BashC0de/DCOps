// Intentional OWASP vulnerable sample for testing scanners.
// Do not deploy in production.

const express = require('express');
const app = express();
const mysql = require('mysql');
const { exec } = require('child_process');

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

app.listen(3000, () => console.log('Vulnerable app listening on port 3000'));
