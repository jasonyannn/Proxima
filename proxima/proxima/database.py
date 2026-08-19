import sqlite3
from pathlib import Path
from typing import Any


class DatabaseManager:
    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            db_path = str(Path(__file__).resolve().parent / "data" / "product.db")
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def init_db(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS feature (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    priority TEXT DEFAULT 'medium',
                    impact TEXT DEFAULT 'medium',
                    effort TEXT DEFAULT 'medium',
                    status TEXT DEFAULT 'planned',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS bug (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    severity TEXT DEFAULT 'medium',
                    status TEXT DEFAULT 'open',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT,
                    content TEXT NOT NULL,
                    sentiment TEXT DEFAULT 'neutral',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.commit()

    def create_feature(
        self,
        title: str,
        description: str | None = None,
        priority: str = "medium",
        impact: str = "medium",
        effort: str = "medium",
        status: str = "planned",
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO feature (title, description, priority, impact, effort, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (title, description, priority, impact, effort, status),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_features(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM feature ORDER BY created_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def create_bug(
        self,
        title: str,
        description: str | None = None,
        severity: str = "medium",
        status: str = "open",
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO bug (title, description, severity, status)
                VALUES (?, ?, ?, ?)
                """,
                (title, description, severity, status),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_bugs(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM bug ORDER BY created_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def create_feedback(
        self,
        source: str | None = None,
        content: str = "",
        sentiment: str = "neutral",
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO feedback (source, content, sentiment)
                VALUES (?, ?, ?)
                """,
                (source, content, sentiment),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_feedback(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM feedback ORDER BY created_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]
