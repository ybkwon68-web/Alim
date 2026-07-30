from datetime import datetime
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import database
import collector
import llm_helper
import notifier

logger = logging.getLogger("AlimBot.Scheduler")

# Global reference to scheduler for dynamic rescheduling
_global_scheduler = None

def process_and_send_user_reports(chat_id, email, schedule_name):
    """
    Collects stock data, filters duplicates, performs AI summarization,
    and sends consolidated Telegram and Email reports to a single user.
    """
    stocks = database.get_user_stocks(chat_id)
    if not stocks:
        logger.info(f"User {chat_id} has no registered stocks. Skipping.")
        return
        
    logger.info(f"Processing scheduled report ({schedule_name}) for user {chat_id}...")
    
    # Load settings
    settings = database.get_user_settings(chat_id)
    telegram_enabled = settings.get("telegram_enabled", 1) if settings else 1
    email_enabled = settings.get("email_enabled", 1) if settings else 1
    
    if not telegram_enabled and not email_enabled:
        logger.info(f"Both alert channels disabled for user {chat_id}. Skipping alerts.")
        return

    summaries = []
    telegram_lines = [f"📅 <b>정기 금융 리포트 ({schedule_name})</b>\n"]
    has_significant_update = False
    
    for stock in stocks:
        ticker = stock["ticker"]
        name = stock["name"]
        
        # 1. Fetch Quote
        quote = collector.fetch_stock_quote(ticker) or collector.fetch_fund_price(ticker)
        if not quote:
            logger.warning(f"Could not fetch quote for {name} ({ticker})")
            continue
            
        # 2. Fetch Disclosures & News (last 12 hours)
        disclosures = collector.fetch_dart_disclosures(ticker, hours=12)
        news = collector.fetch_stock_news(name, ticker, hours=12)
        
        # 3. Deduplicate
        new_disclosures = []
        for d in disclosures:
            item_key = f"disclosure_{d['id']}"
            if not database.is_alert_sent(chat_id, item_key):
                new_disclosures.append(d)
                database.mark_alert_sent(chat_id, item_key)
                
        new_news = []
        for n in news:
            # Create a simple unique hash key based on url
            item_key = f"news_{hash(n['url'])}"
            if not database.is_alert_sent(chat_id, item_key):
                new_news.append(n)
                database.mark_alert_sent(chat_id, item_key)
                
        # 4. Get LLM summary
        summary_res = llm_helper.summarize_stock_data(quote, new_disclosures, new_news)
        summary_res.update(quote)
        
        importance = summary_res.get("importance_score", 2)
        sentiment = summary_res.get("sentiment", "Neutral")
        
        # Flag if any stock has high importance or actual new content
        if importance >= 3 or new_disclosures or new_news:
            has_significant_update = True
            
        summaries.append(summary_res)
        
        # Format Telegram text line
        sign = "+" if quote["change"] > 0 else ""
        color = "🔴" if quote["change"] > 0 else ("🔵" if quote["change"] < 0 else "⚪")
        price_formatted = f"{quote['price']:,}" if quote['currency'] == 'KRW' else f"{quote['price']:.2f}"
        
        telegram_lines.append(
            f"{color} <b>{name}</b> ({ticker})\n"
            f"• 시세: {price_formatted} {quote['currency']} ({sign}{quote['pct_change']:.2f}%)\n"
            f"• 요약: {summary_res.get('summary_telegram')}\n"
        )
        
    # Send Reports & Write History
    if summaries:
        # A. Telegram Alert
        if telegram_enabled:
            # If there are no important updates, we notify with current prices but omit detailed news/summaries to reduce spam.
            # Morning reports and manual triggers ("즉시발송") are always sent in full detail.
            if not has_significant_update and schedule_name not in ("아침", "즉시발송"):
                lines = [f"📅 <b>정기 금융 리포트 ({schedule_name})</b>\n"]
                for s in summaries:
                    sign = "+" if s["change"] > 0 else ""
                    color = "🔴" if s["change"] > 0 else ("🔵" if s["change"] < 0 else "⚪")
                    price_formatted = f"{s['price']:,}" if s['currency'] == 'KRW' else f"{s['price']:.2f}"
                    lines.append(f"{color} <b>{s['name']}</b>: {price_formatted} {s['currency']} ({sign}{s['pct_change']:.2f}%)")
                lines.append("\n• 중대한 새로운 뉴스나 공시는 없습니다. 평온한 상태입니다.")
                telegram_msg = "\n".join(lines)
                notifier.send_telegram_message(chat_id, telegram_msg)
            else:
                telegram_msg = "\n".join(telegram_lines)
                notifier.send_telegram_message(chat_id, telegram_msg)
                
            # Log to History for Telegram
            for s in summaries:
                database.add_alert_history(
                    chat_id=chat_id,
                    ticker=s["ticker"],
                    name=s["name"],
                    price=s["price"],
                    pct_change=s["pct_change"],
                    sentiment=s["sentiment"],
                    summary=s["summary_telegram"],
                    channel="TELEGRAM"
                )
                
        # B. Email Report
        if email_enabled and email:
            if notifier.send_email_report(email, summaries):
                # Log to History for Email
                for s in summaries:
                    database.add_alert_history(
                        chat_id=chat_id,
                        ticker=s["ticker"],
                        name=s["name"],
                        price=s["price"],
                        pct_change=s["pct_change"],
                        sentiment=s["sentiment"],
                        summary=s["summary_email"],
                        channel="EMAIL"
                    )
        elif email_enabled:
            logger.info(f"User {chat_id} has email alerts enabled but no email address registered.")

def run_scheduled_job(schedule_name):
    """
    Job entrypoint called by the scheduler. Queries all active users and triggers report generation.
    """
    logger.info(f"Starting scheduled monitoring job: {schedule_name}")
    users = database.get_all_users_with_stocks()
    for user in users:
        try:
            # user Row contains chat_id and email
            process_and_send_user_reports(user["chat_id"], user["email"], schedule_name)
        except Exception as e:
            logger.error(f"Error processing scheduled report for user {user['chat_id']}: {e}")

def reload_scheduler_jobs():
    """
    Dynamically reschedules the jobs in APScheduler from database settings.
    """
    global _global_scheduler
    if not _global_scheduler:
        logger.warning("Scheduler is not running. Cannot reload jobs.")
        return False
        
    try:
        user = database.get_first_user()
        if not user:
            return False
            
        settings = database.get_user_settings(user["chat_id"])
        if not settings:
            return False
            
        m_h, m_m = map(int, settings.get("morning_time", "08:30").split(":"))
        l_h, l_m = map(int, settings.get("lunch_time", "12:30").split(":"))
        e_h, e_m = map(int, settings.get("evening_time", "18:30").split(":"))
        
        # Reschedule Morning
        _global_scheduler.reschedule_job(
            "morning_report", 
            trigger=CronTrigger(day_of_week="mon-fri", hour=m_h, minute=m_m)
        )
        # Reschedule Lunch
        _global_scheduler.reschedule_job(
            "lunch_report", 
            trigger=CronTrigger(day_of_week="mon-fri", hour=l_h, minute=l_m)
        )
        # Reschedule Evening
        _global_scheduler.reschedule_job(
            "evening_report", 
            trigger=CronTrigger(day_of_week="mon-fri", hour=e_h, minute=e_m)
        )
        
        logger.info(f"Scheduler jobs dynamically rescheduled. Morning: {m_h:02d}:{m_m:02d}, Lunch: {l_h:02d}:{l_m:02d}, Evening: {e_h:02d}:{e_m:02d}")
        return True
    except Exception as e:
        logger.error(f"Error reloading scheduler jobs from database: {e}")
        return False

def start_scheduler():
    """
    Initializes and starts the BackgroundScheduler. Loads initial times from database.
    """
    global _global_scheduler
    _global_scheduler = BackgroundScheduler()
    
    # Load initial settings from DB
    user = database.get_first_user() # Seeds default if empty
    settings = database.get_user_settings(user["chat_id"])
    
    m_time = settings.get("morning_time", "08:30") if settings else "08:30"
    l_time = settings.get("lunch_time", "12:30") if settings else "12:30"
    e_time = settings.get("evening_time", "18:30") if settings else "18:30"
    
    m_h, m_m = map(int, m_time.split(":"))
    l_h, l_m = map(int, l_time.split(":"))
    e_h, e_m = map(int, e_time.split(":"))
    
    # Schedule jobs
    _global_scheduler.add_job(
        run_scheduled_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=m_h, minute=m_m),
        args=["아침"],
        id="morning_report"
    )
    _global_scheduler.add_job(
        run_scheduled_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=l_h, minute=l_m),
        args=["점심"],
        id="lunch_report"
    )
    _global_scheduler.add_job(
        run_scheduled_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=e_h, minute=e_m),
        args=["저녁"],
        id="evening_report"
    )
    
    # Weekly cleanup job (Sunday night) to clear database old logs
    _global_scheduler.add_job(
        database.clear_old_alerts,
        trigger=CronTrigger(day_of_week="sun", hour=23, minute=0),
        args=[7],
        id="db_cleanup"
    )
    
    _global_scheduler.start()
    logger.info(f"Scheduler started successfully. Morning: {m_time}, Lunch: {l_time}, Evening: {e_time}")
    return _global_scheduler
