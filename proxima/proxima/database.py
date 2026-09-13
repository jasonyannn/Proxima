import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


class DatabaseManager:
    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            db_path = str(Path(__file__).resolve().parent / "data" / "product.db")
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def init_db(self) -> None:
        with closing(self.connect()) as connection:
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS competitor (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    website TEXT,
                    positioning TEXT,
                    pricing TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS competitor_feature (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    competitor_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    category TEXT,
                    source_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (competitor_id) REFERENCES competitor (id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ip_assessment (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feature_title TEXT NOT NULL,
                    feature_description TEXT,
                    risk_level TEXT,
                    risk_score REAL,
                    report TEXT,
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
        with closing(self.connect()) as connection:
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
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM feature ORDER BY created_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_feature(self, feature_id: int) -> None:
        with closing(self.connect()) as connection:
            connection.execute("DELETE FROM feature WHERE id = ?", (feature_id,))
            connection.commit()

    def create_bug(
        self,
        title: str,
        description: str | None = None,
        severity: str = "medium",
        status: str = "open",
    ) -> int:
        with closing(self.connect()) as connection:
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
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM bug ORDER BY created_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_bug(self, bug_id: int) -> None:
        with closing(self.connect()) as connection:
            connection.execute("DELETE FROM bug WHERE id = ?", (bug_id,))
            connection.commit()

    def create_feedback(
        self,
        source: str | None = None,
        content: str = "",
        sentiment: str = "neutral",
    ) -> int:
        with closing(self.connect()) as connection:
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
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM feedback ORDER BY created_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    # --- Competitors ---------------------------------------------------

    def delete_feedback(self, feedback_id: int) -> None:
        with closing(self.connect()) as connection:
            connection.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
            connection.commit()

    def upsert_competitor(
        self,
        name: str,
        website: str | None = None,
        positioning: str | None = None,
        pricing: str | None = None,
        notes: str | None = None,
    ) -> int:
        """Insert a competitor, or update it in place if the name already exists."""
        with closing(self.connect()) as connection:
            connection.execute(
                """
                INSERT INTO competitor (name, website, positioning, pricing, notes)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    website = COALESCE(excluded.website, competitor.website),
                    positioning = COALESCE(excluded.positioning, competitor.positioning),
                    pricing = COALESCE(excluded.pricing, competitor.pricing),
                    notes = COALESCE(excluded.notes, competitor.notes)
                """,
                (name, website, positioning, pricing, notes),
            )
            connection.commit()
            row = connection.execute(
                "SELECT id FROM competitor WHERE name = ?", (name,)
            ).fetchone()
            return int(row["id"])

    def list_competitors(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM competitor ORDER BY name"
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_competitor(self, competitor_id: int) -> None:
        with closing(self.connect()) as connection:
            connection.execute(
                "DELETE FROM competitor_feature WHERE competitor_id = ?", (competitor_id,)
            )
            connection.execute("DELETE FROM competitor WHERE id = ?", (competitor_id,))
            connection.commit()

    def create_competitor_feature(
        self,
        competitor_id: int,
        name: str,
        description: str | None = None,
        category: str | None = None,
        source_url: str | None = None,
    ) -> int:
        with closing(self.connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO competitor_feature (competitor_id, name, description, category, source_url)
                VALUES (?, ?, ?, ?, ?)
                """,
                (competitor_id, name, description, category, source_url),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_competitor_features(
        self, competitor_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Competitor features joined with the competitor name."""
        query = """
            SELECT cf.*, c.name AS competitor_name
            FROM competitor_feature cf
            JOIN competitor c ON c.id = cf.competitor_id
        """
        params: tuple[Any, ...] = ()
        if competitor_id is not None:
            query += " WHERE cf.competitor_id = ?"
            params = (competitor_id,)
        query += " ORDER BY c.name, cf.name"
        with closing(self.connect()) as connection:
            rows = connection.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def delete_competitor_feature(self, feature_id: int) -> None:
        with closing(self.connect()) as connection:
            connection.execute(
                "DELETE FROM competitor_feature WHERE id = ?", (feature_id,)
            )
            connection.commit()

    # --- IP / copyright assessments -------------------------------------

    def create_ip_assessment(
        self,
        feature_title: str,
        feature_description: str | None,
        risk_level: str,
        risk_score: float,
        report: str,
    ) -> int:
        with closing(self.connect()) as connection:
            cursor = connection.execute(
                """
                INSERT INTO ip_assessment
                    (feature_title, feature_description, risk_level, risk_score, report)
                VALUES (?, ?, ?, ?, ?)
                """,
                (feature_title, feature_description, risk_level, risk_score, report),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def list_ip_assessments(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM ip_assessment ORDER BY created_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]
