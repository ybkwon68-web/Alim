import sqlite3
import os
from datetime import datetime, timedelta
import logging
from config import DATABASE_PATH

logger = logging.getLogger("AlimBot.Database")

def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create stocks table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            ticker TEXT,
            name TEXT,
            type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (chat_id) REFERENCES users(chat_id) ON DELETE CASCADE,
            UNIQUE(chat_id, ticker)
        )
    """)
    
    # Create sent_alerts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sent_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            item_key TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (chat_id) REFERENCES users(chat_id) ON DELETE CASCADE
        )
    """)
    
    # Create index on sent_alerts for performance
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sent_alerts_key 
        ON sent_alerts(chat_id, item_key)
    """)
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")

def add_user(chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO users (chat_id) VALUES (?)",
            (chat_id,)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Error adding user {chat_id}: {e}")
    finally:
        conn.close()

def update_user_email(chat_id, email):
    add_user(chat_id)  # Ensure user exists
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET email = ? WHERE chat_id = ?",
            (email, chat_id)
        )
        conn.commit()
        logger.info(f"Updated email for user {chat_id} to {email}")
        return True
    except Exception as e:
        logger.error(f"Error updating email for user {chat_id}: {e}")
        return False
    finally:
        conn.close()

def get_user(chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    user = None
    try:
        cursor.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,))
        user = cursor.fetchone()
    except Exception as e:
        logger.error(f"Error getting user {chat_id}: {e}")
    finally:
        conn.close()
    return user

def add_stock(chat_id, ticker, name, stock_type):
    add_user(chat_id)  # Ensure user exists
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO stocks (chat_id, ticker, name, type) VALUES (?, ?, ?, ?)",
            (chat_id, ticker, name, stock_type)
        )
        conn.commit()
        logger.info(f"Added stock {ticker} ({name}) for user {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Error adding stock {ticker} for user {chat_id}: {e}")
        return False
    finally:
        conn.close()

def remove_stock(chat_id, ticker):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM stocks WHERE chat_id = ? AND (ticker = ? OR name = ?)",
            (chat_id, ticker, ticker)
        )
        conn.commit()
        logger.info(f"Removed stock/ticker {ticker} for user {chat_id}")
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error removing stock {ticker} for user {chat_id}: {e}")
        return False
    finally:
        conn.close()

def get_user_stocks(chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    stocks = []
    try:
        cursor.execute("SELECT * FROM stocks WHERE chat_id = ?", (chat_id,))
        stocks = cursor.fetchall()
    except Exception as e:
        logger.error(f"Error getting stocks for user {chat_id}: {e}")
    finally:
        conn.close()
    return stocks

def get_all_users_with_stocks():
    conn = get_db_connection()
    cursor = conn.cursor()
    users = []
    try:
        cursor.execute("SELECT DISTINCT u.chat_id, u.email FROM users u JOIN stocks s ON u.chat_id = s.chat_id")
        users = cursor.fetchall()
    except Exception as e:
        logger.error(f"Error getting users with stocks: {e}")
    finally:
        conn.close()
    return users

def is_alert_sent(chat_id, item_key):
    conn = get_db_connection()
    cursor = conn.cursor()
    is_sent = False
    try:
        cursor.execute(
            "SELECT 1 FROM sent_alerts WHERE chat_id = ? AND item_key = ?",
            (chat_id, item_key)
        )
        is_sent = cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Error checking alert status for key {item_key}: {e}")
    finally:
        conn.close()
    return is_sent

def mark_alert_sent(chat_id, item_key):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO sent_alerts (chat_id, item_key) VALUES (?, ?)",
            (chat_id, item_key)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Error marking alert {item_key} as sent: {e}")
    finally:
        conn.close()

def clear_old_alerts(days=7):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("DELETE FROM sent_alerts WHERE sent_at < ?", (cutoff,))
        conn.commit()
        logger.info(f"Cleared alerts older than {days} days.")
    except Exception as e:
        logger.error(f"Error clearing old alerts: {e}")
    finally:
        conn.close()
