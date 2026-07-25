-- Intentional insecure SQL seed for testing
DROP TABLE IF EXISTS users;
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  username TEXT,
  password TEXT
);
INSERT INTO users (username, password) VALUES ('admin','password123');
INSERT INTO users (username, password) VALUES ('alice','alicepass');
