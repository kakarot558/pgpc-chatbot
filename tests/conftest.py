"""Tests never touch the real database: they use an in-memory SQLite database."""
import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-at-least-32-chars-long"
os.environ["DEBUG"] = "true"
