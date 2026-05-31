#!/usr/bin/env python3
"""
Chinese SRS Review App — Flask backend with SM-2 spaced repetition.
"""

import os
import sqlite3
from datetime import date, timedelta
from flask import Flask, jsonify, request, render_template

app = Flask(__name__)

DB_PATH = os.environ.get(
    "SRS_DB_PATH",
    "data/srs.db",
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def sm2_calculate(easiness, interval, repetitions, quality):
    """
    SM-2 algorithm.
    quality: 0-5 (0=complete blackout, 5=perfect response)
    Returns (new_easiness, new_interval, new_repetitions)
    """
    if quality < 3:
        # Failed — reset
        return (easiness, 1, 0)
    
    # Calculate new easiness factor
    new_ef = easiness + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    if new_ef < 1.3:
        new_ef = 1.3
    
    if repetitions == 0:
        new_interval = 1
    elif repetitions == 1:
        new_interval = 6
    else:
        new_interval = round(interval * new_ef)
    
    return (new_ef, new_interval, repetitions + 1)


# ─── API Routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/stats")
def api_stats():
    conn = get_db()
    today = date.today().isoformat()
    
    stats = {}
    
    # Cards due today
    stats["due_today"] = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE next_review <= ? AND is_active = 1",
        (today,),
    ).fetchone()[0]
    
    # New cards (never reviewed)
    stats["new_cards"] = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE repetitions = 0 AND is_active = 1"
    ).fetchone()[0]
    
    # Total active
    stats["total_active"] = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE is_active = 1"
    ).fetchone()[0]
    
    # Total cards
    stats["total_cards"] = conn.execute(
        "SELECT COUNT(*) FROM cards"
    ).fetchone()[0]
    
    # Breakdown by type
    for row in conn.execute(
        "SELECT card_type, COUNT(*) as cnt FROM cards WHERE is_active = 1 GROUP BY card_type"
    ):
        stats[f"{row['card_type']}_count"] = row["cnt"]
    
    # Due breakdown by type
    for row in conn.execute(
        "SELECT card_type, COUNT(*) as cnt FROM cards WHERE next_review <= ? AND is_active = 1 GROUP BY card_type",
        (today,),
    ):
        stats[f"{row['card_type']}_due"] = row["cnt"]
    
    # Cards due in next 7 days (excluding today)
    next_week = (date.today() + timedelta(days=7)).isoformat()
    stats["due_week"] = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE next_review > ? AND next_review <= ? AND is_active = 1",
        (today, next_week),
    ).fetchone()[0]
    
    # Reviews done today
    stats["reviewed_today"] = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE last_reviewed = ?",
        (today,),
    ).fetchone()[0]
    
    conn.close()
    return jsonify(stats)


@app.route("/api/review/next")
def api_review_next():
    """Get the next card due for review.
    
    Returns a mixed batch: reviewed cards (due/overdue) first, ordered by
    urgency, then new cards to fill remaining slots. This ensures failed
    cards surface immediately while new cards remain discoverable.
    """
    conn = get_db()
    today = date.today().isoformat()
    
    card_type = request.args.get("type", "")
    limit = min(int(request.args.get("limit", 1)), 50)
    
    base_where = "WHERE next_review <= ? AND is_active = 1"
    base_params = [today]
    type_clause = ""
    type_params = []
    
    if card_type in ("vocab", "grammar", "phrase"):
        type_clause = " AND card_type = ?"
        type_params = [card_type]
    
    # 1) Fetch reviewed cards due/overdue — these are the priority
    rows = conn.execute(f"""
        SELECT * FROM cards {base_where}{type_clause}
        AND last_reviewed IS NOT NULL
        ORDER BY next_review ASC, easiness ASC, repetitions ASC, RANDOM()
        LIMIT ?
    """, base_params + type_params + [limit]).fetchall()
    
    cards = []
    for row in rows:
        cards.append({
            "id": row["id"],
            "card_type": row["card_type"],
            "front": row["front"],
            "back": row["back"],
            "pinyin": row["pinyin"],
            "category": row["category"],
            "theme": row["theme"],
            "source_day": row["source_day"],
            "easiness": row["easiness"],
            "interval": row["interval"],
            "repetitions": row["repetitions"],
            "next_review": row["next_review"],
        })
    
    # 2) Fill remaining slots with new cards (never reviewed)
    remaining = limit - len(cards)
    if remaining > 0:
        rows = conn.execute(f"""
            SELECT * FROM cards {base_where}{type_clause}
            AND last_reviewed IS NULL
            ORDER BY next_review ASC, RANDOM()
            LIMIT ?
        """, base_params + type_params + [remaining]).fetchall()
        
        for row in rows:
            cards.append({
                "id": row["id"],
                "card_type": row["card_type"],
                "front": row["front"],
                "back": row["back"],
                "pinyin": row["pinyin"],
                "category": row["category"],
                "theme": row["theme"],
                "source_day": row["source_day"],
                "easiness": row["easiness"],
                "interval": row["interval"],
                "repetitions": row["repetitions"],
                "next_review": row["next_review"],
            })
    
    conn.close()
    return jsonify({"cards": cards, "count": len(cards)})


@app.route("/api/review/new", methods=["GET"])
def api_review_new():
    """Get cards that have never been reviewed (repetitions = 0)."""
    conn = get_db()
    card_type = request.args.get("type", "")
    limit = min(int(request.args.get("limit", 10)), 50)
    
    query = "SELECT * FROM cards WHERE repetitions = 0 AND is_active = 1"
    params = []
    
    if card_type in ("vocab", "grammar", "phrase"):
        query += " AND card_type = ?"
        params.append(card_type)
    
    query += " ORDER BY RANDOM() LIMIT ?"
    params.append(limit)
    
    rows = conn.execute(query, params).fetchall()
    
    cards = []
    for row in rows:
        cards.append({
            "id": row["id"],
            "card_type": row["card_type"],
            "front": row["front"],
            "back": row["back"],
            "pinyin": row["pinyin"],
            "category": row["category"],
            "theme": row["theme"],
            "source_day": row["source_day"],
        })
    
    conn.close()
    return jsonify({"cards": cards, "count": len(cards)})


@app.route("/api/review", methods=["POST"])
def api_review_submit():
    """Submit a review rating for a card."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    card_id = data.get("card_id")
    quality = data.get("quality")
    
    if not card_id or quality is None:
        return jsonify({"error": "card_id and quality required"}), 400
    
    if quality < 0 or quality > 5:
        return jsonify({"error": "quality must be 0-5"}), 400
    
    conn = get_db()
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    
    if not row:
        conn.close()
        return jsonify({"error": "Card not found"}), 404
    
    easiness, interval, repetitions = sm2_calculate(
        row["easiness"], row["interval"], row["repetitions"], quality
    )
    
    today = date.today()
    next_review = today + timedelta(days=interval)
    
    # Update card
    conn.execute(
        """
        UPDATE cards 
        SET easiness = ?, interval = ?, repetitions = ?, 
            next_review = ?, last_reviewed = ?, is_active = 1
        WHERE id = ?
        """,
        (round(easiness, 2), interval, repetitions, 
         next_review.isoformat(), today.isoformat(), card_id),
    )
    conn.commit()
    conn.close()
    
    return jsonify({
        "success": True,
        "next_review": next_review.isoformat(),
        "interval": interval,
        "repetitions": repetitions,
        "easiness": round(easiness, 2),
    })


@app.route("/api/cards")
def api_list_cards():
    """List/filter cards."""
    conn = get_db()
    card_type = request.args.get("type", "")
    category = request.args.get("category", "")
    search = request.args.get("search", "")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))
    
    query = "SELECT * FROM cards WHERE is_active = 1"
    params = []
    
    if card_type in ("vocab", "grammar", "phrase"):
        query += " AND card_type = ?"
        params.append(card_type)
    
    if category:
        query += " AND category LIKE ?"
        params.append(f"%{category}%")
    
    if search:
        query += " AND (front LIKE ? OR back LIKE ? OR pinyin LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s])
    
    count = conn.execute(
        query.replace("SELECT *", "SELECT COUNT(*)"), params
    ).fetchone()[0]
    
    query += " ORDER BY CASE WHEN last_reviewed IS NULL THEN 2 WHEN repetitions = 0 THEN 0 ELSE 1 END, easiness ASC, next_review ASC, CASE card_type WHEN 'vocab' THEN 1 WHEN 'grammar' THEN 2 WHEN 'phrase' THEN 3 ELSE 4 END, front ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    rows = conn.execute(query, params).fetchall()
    
    cards = []
    for row in rows:
        cards.append({
            "id": row["id"],
            "card_type": row["card_type"],
            "front": row["front"],
            "back": row["back"],
            "pinyin": row["pinyin"],
            "category": row["category"],
            "theme": row["theme"],
            "source_day": row["source_day"],
            "easiness": row["easiness"],
            "interval": row["interval"],
            "repetitions": row["repetitions"],
            "next_review": row["next_review"],
            "last_reviewed": row["last_reviewed"],
        })
    
    conn.close()
    return jsonify({"cards": cards, "count": count, "total": len(cards)})


@app.route("/api/categories")
def api_categories():
    """List all unique categories/themes."""
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT category FROM cards WHERE category != '' AND is_active = 1 ORDER BY category"
    ).fetchall()
    
    categories = [row["category"] for row in rows]
    conn.close()
    return jsonify({"categories": categories})


@app.route("/api/themes")
def api_themes():
    """List all themes by day."""
    conn = get_db()
    rows = conn.execute(
        "SELECT day_number, theme_name FROM themes ORDER BY day_number"
    ).fetchall()
    
    themes = [{"day": row["day_number"], "theme": row["theme_name"]} for row in rows]
    conn.close()
    return jsonify({"themes": themes})


@app.route("/api/card/<int:card_id>")
def api_get_card(card_id):
    """Get a single card by ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    conn.close()
    
    if not row:
        return jsonify({"error": "Card not found"}), 404
    
    return jsonify({
        "id": row["id"],
        "card_type": row["card_type"],
        "front": row["front"],
        "back": row["back"],
        "pinyin": row["pinyin"],
        "category": row["category"],
        "theme": row["theme"],
        "source_day": row["source_day"],
        "easiness": row["easiness"],
        "interval": row["interval"],
        "repetitions": row["repetitions"],
        "next_review": row["next_review"],
        "last_reviewed": row["last_reviewed"],
    })


@app.route("/api/reset", methods=["POST"])
def api_reset_card():
    """Reset a card to new/unreviewed state."""
    data = request.get_json()
    card_id = data.get("card_id")
    
    if not card_id:
        return jsonify({"error": "card_id required"}), 400
    
    conn = get_db()
    conn.execute(
        """
        UPDATE cards 
        SET easiness = 2.5, interval = 0, repetitions = 0, 
            next_review = date('now'), last_reviewed = NULL
        WHERE id = ?
        """,
        (card_id,),
    )
    conn.commit()
    conn.close()
    
    return jsonify({"success": True})


@app.route("/api/review/session", methods=["POST"])
def api_review_all_due():
    """Submit multiple reviews at once (for batch operations)."""
    data = request.get_json()
    if not data or "reviews" not in data:
        return jsonify({"error": "reviews array required"}), 400
    
    conn = get_db()
    today = date.today()
    today_str = today.isoformat()
    results = []
    
    for review in data["reviews"]:
        card_id = review.get("card_id")
        quality = review.get("quality")
        
        if not card_id or quality is None:
            results.append({"card_id": card_id, "error": "Missing card_id or quality"})
            continue
        
        if quality < 0 or quality > 5:
            results.append({"card_id": card_id, "error": "quality must be 0-5"})
            continue
        
        row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not row:
            results.append({"card_id": card_id, "error": "Not found"})
            continue
        
        easiness, interval, repetitions = sm2_calculate(
            row["easiness"], row["interval"], row["repetitions"], quality
        )
        
        next_review = today + timedelta(days=interval)
        
        conn.execute(
            """
            UPDATE cards 
            SET easiness = ?, interval = ?, repetitions = ?, 
                next_review = ?, last_reviewed = ?
            WHERE id = ?
            """,
            (round(easiness, 2), interval, repetitions, 
             next_review.isoformat(), today_str, card_id),
        )
        
        results.append({
            "card_id": card_id,
            "success": True,
            "next_review": next_review.isoformat(),
            "interval": interval,
        })
    
    conn.commit()
    conn.close()
    
    return jsonify({"results": results, "count": len(results)})


@app.route("/api/activity")
def api_activity():
    """Get review activity for the past N days."""
    days = min(int(request.args.get("days", 30)), 365)
    conn = get_db()
    
    start = (date.today() - timedelta(days=days - 1)).isoformat()
    
    rows = conn.execute(
        """
        SELECT last_reviewed as day, COUNT(*) as reviews,
               SUM(CASE WHEN repetitions = 1 THEN 1 ELSE 0 END) as new_learned
        FROM cards 
        WHERE last_reviewed >= ? AND last_reviewed IS NOT NULL
        GROUP BY last_reviewed
        ORDER BY last_reviewed
        """,
        (start,),
    ).fetchall()
    
    activity = {}
    for row in rows:
        activity[row["day"]] = {
            "reviews": row["reviews"],
            "new_learned": row["new_learned"],
        }
    
    conn.close()
    return jsonify({"activity": activity, "days": days})


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
