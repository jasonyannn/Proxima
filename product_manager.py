"""
product_manager.py

Product Manager functions for features, bugs, feedback, backlog retrieval,
updates, prioritisation and simple sprint generation.

Storage: SQLite file 'backlog.db' in the repository root.

Functions:
- create_feature(...)
- create_bug(...)
- create_feedback(...)
- get_backlog()
- update_feature()
- prioritise_backlog()
- generate_sprint()

This module is intentionally lightweight and framework-agnostic so it can be
called from a Flask/FastAPI route or a CLI.
"""

from typing import Optional, List, Dict, Any, Tuple
import sqlite3
import os
import datetime
from dataclasses import dataclass, asdict

DB_PATH = os.path.join(os.path.dirname(__file__), "backlog.db")

# --- Utilities ----------------------------------------------------------------

def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL, -- feature | bug | feedback
        title TEXT NOT NULL,
        description TEXT,
        priority TEXT,
        impact INTEGER,
        reach INTEGER,
        urgency INTEGER,
        effort REAL,
        score REAL,
        metadata TEXT,
        created_at TEXT NOT NULL
    )
    """)
    conn.commit()
    conn.close()


# Ensure DB exists on import
_init_db()


# --- Mapping helpers ----------------------------------------------------------

def _scale_from_value(v: Optional[Any]) -> Optional[float]:
    """Accept numeric or descriptive strings and return a numeric scale (1-5).

    Examples:
      'Low' -> 1, 'Medium' -> 3, 'High' -> 5
      Numeric values are returned as-is.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("low", "l"):
            return 1.0
        if s in ("medium", "med", "m"):
            return 3.0
        if s in ("high", "h"):
            return 5.0
        # try parse number
        try:
            return float(s)
        except ValueError:
            return None
    return None


# --- Data model helpers -------------------------------------------------------

@dataclass
class BacklogItem:
    id: Optional[int]
    type: str
    title: str
    description: Optional[str]
    priority: Optional[str]
    impact: Optional[float]
    reach: Optional[float]
    urgency: Optional[float]
    effort: Optional[float]
    score: Optional[float]
    metadata: Optional[str]
    created_at: str

    @staticmethod
    def from_row(row: sqlite3.Row) -> "BacklogItem":
        return BacklogItem(
            id=row["id"],
            type=row["type"],
            title=row["title"],
            description=row["description"],
            priority=row["priority"],
            impact=row["impact"],
            reach=row["reach"],
            urgency=row["urgency"],
            effort=row["effort"],
            score=row["score"],
            metadata=row["metadata"],
            created_at=row["created_at"],
        )


# --- Core functions -----------------------------------------------------------

def create_feature(title: str,
                   description: Optional[str] = None,
                   impact: Optional[Any] = None,
                   reach: Optional[Any] = None,
                   urgency: Optional[Any] = None,
                   effort: Optional[Any] = None,
                   priority: Optional[str] = None,
                   metadata: Optional[str] = None) -> int:
    """Create a backlog feature and return its id."""
    imp = _scale_from_value(impact)
    rch = _scale_from_value(reach)
    urg = _scale_from_value(urgency)
    eff = None
    if effort is not None:
        try:
            eff = float(effort)
        except Exception:
            eff = None

    score = None
    if imp is not None and rch is not None and urg is not None and eff not in (None, 0):
        score = (imp * rch * urg) / eff

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO items (type, title, description, priority, impact, reach, urgency, effort, score, metadata, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("feature", title, description, priority, imp, rch, urg, eff, score, metadata, datetime.datetime.utcnow().isoformat()),
    )
    conn.commit()
    item_id = cur.lastrowid
    conn.close()
    return item_id


def create_bug(title: str,
               description: Optional[str] = None,
               severity: Optional[Any] = None,
               metadata: Optional[str] = None) -> int:
    """Create a bug item. severity can be 'Low/Medium/High' or numeric."""
    sev = _scale_from_value(severity)
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO items (type, title, description, priority, metadata, created_at) VALUES (?,?,?,?,?,?)",
        ("bug", title, description, None, metadata, datetime.datetime.utcnow().isoformat()),
    )
    conn.commit()
    item_id = cur.lastrowid
    conn.close()
    return item_id


def create_feedback(title: str,
                    description: Optional[str] = None,
                    rating: Optional[Any] = None,
                    metadata: Optional[str] = None) -> int:
    """Create a feedback item. rating can be a number or descriptive string."""
    rat = _scale_from_value(rating)
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO items (type, title, description, priority, metadata, created_at) VALUES (?,?,?,?,?,?)",
        ("feedback", title, description, None, metadata, datetime.datetime.utcnow().isoformat()),
    )
    conn.commit()
    item_id = cur.lastrowid
    conn.close()
    return item_id


def get_backlog(kind: Optional[str] = None, order_by: str = "created_at") -> List[Dict[str, Any]]:
    """Return backlog items. kind can be 'feature', 'bug', 'feedback' or None for all."""
    conn = _get_conn()
    cur = conn.cursor()
    q = "SELECT * FROM items"
    params: Tuple = ()
    if kind:
        q += " WHERE type = ?"
        params = (kind,)
    if order_by not in ("created_at", "score", "priority"):
        order_by = "created_at"
    q += f" ORDER BY {order_by} DESC"
    cur.execute(q, params)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_feature(item_id: int, **fields) -> bool:
    """Update a feature's fields. Accepts impact, reach, urgency, effort, priority, title, description."""
    allowed = {"impact", "reach", "urgency", "effort", "priority", "title", "description", "metadata"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    # Normalize numeric scales
    if "impact" in updates:
        updates["impact"] = _scale_from_value(updates["impact"])
    if "reach" in updates:
        updates["reach"] = _scale_from_value(updates["reach"])
    if "urgency" in updates:
        updates["urgency"] = _scale_from_value(updates["urgency"])
    if "effort" in updates and updates["effort"] is not None:
        try:
            updates["effort"] = float(updates["effort"])
        except Exception:
            updates["effort"] = None

    # Recompute score if possible
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT impact, reach, urgency, effort FROM items WHERE id = ?", (item_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False
    impact = updates.get("impact", row["impact"])
    reach = updates.get("reach", row["reach"])
    urgency = updates.get("urgency", row["urgency"])
    effort = updates.get("effort", row["effort"])

    score = None
    if impact is not None and reach is not None and urgency is not None and effort not in (None, 0):
        try:
            score = (float(impact) * float(reach) * float(urgency)) / float(effort)
        except Exception:
            score = None

    # Build SQL
    set_clauses = []
    params = []
    for k, v in updates.items():
        set_clauses.append(f"{k} = ?")
        params.append(v)
    set_clauses.append("score = ?")
    params.append(score)
    params.append(item_id)

    sql = f"UPDATE items SET {', '.join(set_clauses)} WHERE id = ?"
    cur.execute(sql, params)
    conn.commit()
    conn.close()
    return True


def prioritise_backlog(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Compute priority scores for all features and return a ranked list with explanation.

    Score formula used:
        score = (impact * reach * urgency) / effort

    impact/reach/urgency/effort accept numeric values or descriptive strings.
    """
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM items WHERE type = 'feature'")
    rows = cur.fetchall()

    ranked: List[Tuple[float, sqlite3.Row]] = []
    explanations: List[Dict[str, Any]] = []

    for r in rows:
        imp = r["impact"]
        rch = r["reach"]
        urg = r["urgency"]
        eff = r["effort"]
        score = None
        if imp is not None and rch is not None and urg is not None and eff not in (None, 0):
            try:
                score = (float(imp) * float(rch) * float(urg)) / float(eff)
            except Exception:
                score = None
        # Update DB score
        cur.execute("UPDATE items SET score = ? WHERE id = ?", (score, r["id"]))
        ranked.append(((score or 0.0), r))

    conn.commit()

    # Sort high to low
    ranked.sort(key=lambda t: (t[0] if t[0] is not None else 0.0), reverse=True)

    # Limit
    if limit is not None:
        ranked = ranked[:limit]

    result: List[Dict[str, Any]] = []
    for score, row in ranked:
        explanation = ""
        if score is None:
            explanation = "Insufficient data to compute score."
        else:
            explanation = f"Score={score:.2f} (impact={row['impact']}, reach={row['reach']}, urgency={row['urgency']}, effort={row['effort']})"
        result.append({**dict(row), "computed_score": score, "explanation": explanation})

    conn.close()
    return result


def generate_sprint(capacity: float = 10.0, num_items: Optional[int] = None) -> List[Dict[str, Any]]:
    """Generate a sprint from the prioritised backlog.

    Simple greedy algorithm: pick highest score features until capacity (sum of effort) is reached.
    capacity: total effort points available (e.g., developer-days or story points)
    num_items: optional cap on number of items
    """
    ranked = prioritise_backlog()
    sprint: List[Dict[str, Any]] = []
    used = 0.0

    for item in ranked:
        eff = item.get("effort") or 0.0
        # skip items without effort estimate
        if eff is None:
            continue
        if used + float(eff) > capacity:
            continue
        sprint.append(item)
        used += float(eff)
        if num_items is not None and len(sprint) >= num_items:
            break

    return sprint


# --- Feedback analysis and dashboard ---------------------------------------

STOPWORDS = {
    "the", "is", "and", "a", "an", "to", "of", "in", "on", "for", "i", "you",
    "it", "that", "this", "can't", "cant", "please", "can", "be", "are", "with",
    "we", "our", "us", "not", "so", "if", "or", "as", "from", "by"
}
PAIN_KEYWORDS = {"hate", "can't", "cant", "impossible", "frustrat", "annoy", "broken", "bug", "issue", "problem"}


def _tokenize(text: str) -> List[str]:
    text = (text or "").lower()
    # simple tokenisation: keep alphanumerics
    tokens = []
    cur = []
    for ch in text:
        if ch.isalnum():
            cur.append(ch)
        else:
            if cur:
                tokens.append(''.join(cur))
                cur = []
    if cur:
        tokens.append(''.join(cur))
    return [t for t in tokens if t and t not in STOPWORDS]


def extract_themes_from_texts(texts: List[str], min_count: int = 2, top_n: int = 10) -> List[Tuple[str, int]]:
    """Extract frequent tokens/themes from a list of texts.

    Returns list of (token, count) sorted by count desc.
    """
    counts: Dict[str, int] = {}
    for text in texts:
        tokens = _tokenize(text)
        # count unique tokens per text to avoid duplicates inflating counts
        seen = set()
        for t in tokens:
            if t in seen:
                continue
            seen.add(t)
            counts[t] = counts.get(t, 0) + 1
    items = [(k, v) for k, v in counts.items() if v >= min_count]
    items.sort(key=lambda x: x[1], reverse=True)
    return items[:top_n]


def group_similar_feedback(feedback_rows: List[Dict[str, Any]], themes: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Group feedback rows by simple theme matching (keyword in text).

    feedback_rows: list of dicts with 'id', 'title', 'description'
    themes: list of theme keywords
    """
    groups: Dict[str, List[Dict[str, Any]]] = {t: [] for t in themes}
    other: List[Dict[str, Any]] = []
    for r in feedback_rows:
        text = ((r.get('title') or '') + ' ' + (r.get('description') or '')).lower()
        matched = False
        for t in themes:
            if t in text:
                groups[t].append(r)
                matched = True
        if not matched:
            other.append(r)
    if other:
        groups['other'] = other
    return groups


def identify_customer_pain(feedback_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Identify count of feedbacks that contain explicit pain indicators and examples."""
    pain_count = 0
    examples: List[Dict[str, Any]] = []
    for r in feedback_rows:
        text = ((r.get('title') or '') + ' ' + (r.get('description') or '')).lower()
        if any(pk in text for pk in PAIN_KEYWORDS):
            pain_count += 1
            if len(examples) < 5:
                examples.append(r)
    return {"pain_count": pain_count, "examples": examples}


def recommend_features_for_themes(themes: List[str]) -> List[Dict[str, str]]:
    """Return simple feature recommendations for each theme using heuristics."""
    recs: List[Dict[str, str]] = []
    for t in themes:
        name = None
        t_lower = t.lower()
        if 'search' in t_lower:
            name = 'Global Search'
            desc = 'Add a global search bar that indexes projects, tasks and content.'
        elif 'mobile' in t_lower or 'phone' in t_lower:
            name = 'Improve Mobile UX'
            desc = 'Improve responsiveness and mobile-first layout for small screens.'
        elif 'perform' in t_lower or 'speed' in t_lower or 'latency' in t_lower:
            name = 'Performance Improvements'
            desc = 'Investigate and optimise slow paths (queries, rendering, assets).'
        elif 'export' in t_lower or 'csv' in t_lower or 'download' in t_lower:
            name = 'Export / Data Export'
            desc = 'Provide CSV/JSON export for common reports and entities.'
        elif 'auth' in t_lower or 'login' in t_lower or 'signup' in t_lower:
            name = 'Improve Authentication Flow'
            desc = 'Streamline login/signup and recovery flows.'
        else:
            name = f'Investigation: {t}'
            desc = f'Investigate customer requests around "{t}" and propose a targeted feature.'
        recs.append({"theme": t, "recommendation": name, "description": desc})
    return recs


def analyze_feedback(min_theme_count: int = 2, top_n: int = 10) -> Dict[str, Any]:
    """Run analysis over all feedback items in the backlog and return themes, groups, pain and recommendations."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, title, description, created_at FROM items WHERE type = 'feedback'")
    rows = cur.fetchall()
    feedback_rows = [dict(r) for r in rows]
    conn.close()

    texts = [((r.get('title') or '') + ' ' + (r.get('description') or '')) for r in feedback_rows]
    theme_counts = extract_themes_from_texts(texts, min_count=min_theme_count, top_n=top_n)
    themes = [t for t, _ in theme_counts]
    groups = group_similar_feedback(feedback_rows, themes)
    pain = identify_customer_pain(feedback_rows)
    recommendations = recommend_features_for_themes(themes)

    return {
        "total_feedback": len(feedback_rows),
        "themes": theme_counts,
        "groups": {k: v for k, v in groups.items()},
        "pain": pain,
        "recommendations": recommendations,
    }


def generate_dashboard(top_feedback_themes: int = 5) -> Dict[str, Any]:
    """Return a dashboard summary with backlog, bugs, and customer feedback stats."""
    conn = _get_conn()
    cur = conn.cursor()
    # Backlog counts by priority for features
    cur.execute("SELECT priority, COUNT(1) as c FROM items WHERE type = 'feature' GROUP BY priority")
    features_counts = {row['priority'] or 'Unspecified': row['c'] for row in cur.fetchall()}
    # Bugs by priority
    cur.execute("SELECT priority, COUNT(1) as c FROM items WHERE type = 'bug' GROUP BY priority")
    bugs_counts = {row['priority'] or 'Unspecified': row['c'] for row in cur.fetchall()}
    # Feedback totals and top themes
    cur.execute("SELECT id, title, description FROM items WHERE type = 'feedback'")
    feedback_rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    texts = [((r.get('title') or '') + ' ' + (r.get('description') or '')) for r in feedback_rows]
    theme_counts = extract_themes_from_texts(texts, min_count=1, top_n=top_feedback_themes)

    dashboard = {
        "backlog": features_counts,
        "bugs": bugs_counts,
        "customer_feedback": {
            "total": len(feedback_rows),
            "top_themes": theme_counts,
        }
    }
    return dashboard


# --- Small CLI/demo ----------------------------------------------------------

if __name__ == "__main__":
    print("Product Manager module demo")
    # Create demo items if DB empty
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(1) as c FROM items")
    c = cur.fetchone()["c"]
    conn.close()
    if c == 0:
        print("Seeding demo backlog...")
        create_feature("Dark Mode", "Add dark theme to UI", impact=5, reach=5, urgency=4, effort=2, priority="High")
        create_feature("Export CSV", "Allow exporting user data", impact=3, reach=4, urgency=2, effort=3, priority="Medium")
        create_feature("Mobile Layout", "Improve mobile responsiveness", impact=4, reach=5, urgency=3, effort=5, priority="High")
        # Seed feedback examples
        create_feedback("I hate that I can't search.", "Finding projects is impossible without search.")
        create_feedback("Please add search", "Would be great to have a search bar to find projects quickly.")
        create_feedback("Finding old projects is impossible", "I often cannot find old work when I need it.")
        create_feedback("Can you add a search bar?", "Search would save time.")
        create_feedback("App is slow", "The app feels laggy when loading dashboards.")
        create_feedback("Mobile layout is broken", "On my phone the UI overflows and is hard to use.")

    print("Top priorities:")
    for i, it in enumerate(prioritise_backlog(limit=10), start=1):
        print(f"{i}. {it['title']} - {it['explanation']}")

    print("Suggested sprint (capacity=6):")
    for it in generate_sprint(capacity=6):
        print(f"- {it['title']} (effort={it['effort']})")

    print("\nFeedback analysis:")
    analysis = analyze_feedback()
    print(f"Total feedback: {analysis['total_feedback']}")
    print("Top themes:")
    for theme, count in analysis['themes']:
        print(f" - {theme}: {count}")
    print("Recommendations:")
    for r in analysis['recommendations']:
        print(f" - {r['theme']} => {r['recommendation']}: {r['description']}")

    print("\nDashboard summary:")
    db = generate_dashboard()
    print("Backlog:")
    for k, v in db['backlog'].items():
        print(f" {k}: {v}")
    print("Bugs:")
    for k, v in db['bugs'].items():
        print(f" {k}: {v}")
    print("Customer Feedback:")
    print(f" Total: {db['customer_feedback']['total']}")
    print(" Top themes:")
    for theme, count in db['customer_feedback']['top_themes']:
        print(f"  - {theme}: {count}")
