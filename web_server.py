import logging
from flask import Flask, render_template, jsonify, request
import database
import collector
import scheduler

logger = logging.getLogger("AlimBot.WebServer")

# Initialize Flask app
app = Flask(__name__)

# Disable default Flask request logging to keep console output clean (optional, but good)
log = logging.getLogger('werkzeug')
log.setLevel(logging.WARNING)

@app.route("/")
def index():
    """
    Renders the admin dashboard webpage.
    """
    return render_template("dashboard.html")

@app.route("/api/data", methods=["GET"])
def get_data():
    """
    Returns user settings and registered stock list.
    """
    try:
        user = database.get_first_user()
        if not user:
            return jsonify({"error": "No users found"}), 404
            
        chat_id = user["chat_id"]
        settings = database.get_user_settings(chat_id)
        stocks = database.get_user_stocks(chat_id)
        
        # Convert sqlite row objects to dictionaries
        stocks_list = [dict(s) for s in stocks]
        
        return jsonify({
            "user": {
                "chat_id": chat_id,
                "email": settings.get("email", ""),
                "telegram_enabled": bool(settings.get("telegram_enabled", 1)),
                "email_enabled": bool(settings.get("email_enabled", 1)),
                "morning_time": settings.get("morning_time", "08:30"),
                "lunch_time": settings.get("lunch_time", "12:30"),
                "evening_time": settings.get("evening_time", "18:30")
            },
            "stocks": stocks_list
        })
    except Exception as e:
        logger.error(f"Error fetching dashboard data: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/settings", methods=["POST"])
def save_settings():
    """
    Updates user receiver settings and alarm timings.
    Trigger reload on background scheduler.
    """
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Invalid request payload"}), 400
            
        user = database.get_first_user()
        chat_id = user["chat_id"]
        
        email = data.get("email", "").strip()
        telegram_enabled = 1 if data.get("telegram_enabled") else 0
        email_enabled = 1 if data.get("email_enabled") else 0
        
        morning_time = data.get("morning_time", "08:30")
        lunch_time = data.get("lunch_time", "12:30")
        evening_time = data.get("evening_time", "18:30")
        
        # Validate time format HH:MM
        time_regex = r"^(0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]$"
        import re
        if not (re.match(time_regex, morning_time) and re.match(time_regex, lunch_time) and re.match(time_regex, evening_time)):
            return jsonify({"error": "Invalid time format (must be HH:MM)"}), 400
            
        # Save to DB
        success = database.update_user_settings(
            chat_id=chat_id,
            email=email,
            telegram_enabled=telegram_enabled,
            email_enabled=email_enabled,
            morning_time=morning_time,
            lunch_time=lunch_time,
            evening_time=evening_time
        )
        
        if success:
            # Reschedule jobs dynamically
            scheduler.reload_scheduler_jobs()
            return jsonify({"message": "Settings updated successfully"})
        else:
            return jsonify({"error": "Failed to update database"}), 500
            
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/stock/add", methods=["POST"])
def add_stock():
    """
    Resolves query and adds stock to interest list.
    """
    try:
        data = request.json
        if not data or not data.get("query"):
            return jsonify({"error": "Stock name or code is required"}), 400
            
        query = data.get("query").strip()
        user = database.get_first_user()
        chat_id = user["chat_id"]
        
        candidates = collector.resolve_stock(query)
        if not candidates:
            return jsonify({"error": "Matching stock not found"}), 404
            
        best_match = candidates[0]
        ticker = best_match["ticker"]
        name = best_match["name"]
        stock_type = best_match["type"]
        
        # Save to DB
        success = database.add_stock(chat_id, ticker, name, stock_type)
        if success:
            return jsonify({
                "message": f"Successfully added {name} ({ticker})",
                "stock": {
                    "ticker": ticker,
                    "name": name,
                    "type": stock_type
                }
            })
        else:
            return jsonify({"error": "Stock already exists in your list"}), 409
            
    except Exception as e:
        logger.error(f"Error adding stock: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/stock/delete", methods=["POST"])
def delete_stock():
    """
    Deletes stock from interest list.
    """
    try:
        data = request.json
        if not data or not data.get("ticker"):
            return jsonify({"error": "Ticker is required"}), 400
            
        ticker = data.get("ticker").strip()
        user = database.get_first_user()
        chat_id = user["chat_id"]
        
        success = database.remove_stock(chat_id, ticker)
        if success:
            return jsonify({"message": f"Successfully deleted stock {ticker}"})
        else:
            return jsonify({"error": "Stock not found in your list"}), 44
            
    except Exception as e:
        logger.error(f"Error deleting stock: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/history", methods=["GET"])
def get_history():
    """
    Returns recent alert history log.
    """
    try:
        history = database.get_alert_history(limit=50)
        return jsonify(history)
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/trigger-alert", methods=["POST"])
def trigger_alert():
    """
    Manually triggers the report generation and delivery.
    """
    try:
        scheduler.run_scheduled_job("즉시발송")
        return jsonify({"message": "수동 즉시 발송이 완료되었습니다."})
    except Exception as e:
        logger.error(f"Error triggering manual alert: {e}")
        return jsonify({"error": str(e)}), 500

