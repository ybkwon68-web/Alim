from datetime import datetime
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import database
import collector
import llm_helper
import notifier

logger = logging.getLogger("AlimBot.Scheduler")

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
        # Even if there is no new news, we still pass quote to summarize the price status
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
        
    # Send Telegram Consolidated Alert
    if summaries:
        # If there are no important updates, we notify briefly to reduce spam,
        # but morning alerts are always sent in full.
        if not has_significant_update and schedule_name != "아침":
            notifier.send_telegram_message(
                chat_id, 
                f"📅 <b>정기 금융 리포트 ({schedule_name})</b>\n\n"
                "• 관심 종목에 대한 중대한 시세 변동이나 새로운 뉴스/공시가 없습니다. 평온한 상태입니다."
            )
        else:
            telegram_msg = "\n".join(telegram_lines)
            notifier.send_telegram_message(chat_id, telegram_msg)
            
        # Send Email Report (only if email is registered)
        if email:
            notifier.send_email_report(email, summaries)
        else:
            logger.info(f"User {chat_id} has no registered email. Skipping email report.")

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

def start_scheduler():
    """
    Initializes and starts the BackgroundScheduler with morning, lunch, and evening times.
    """
    scheduler = BackgroundScheduler()
    
    # Scheduled times: Morning (08:30), Lunch (12:30), Evening (18:30)
    # Weekdays Monday to Friday (mon-fri) is standard for stock markets
    scheduler.add_job(
        run_scheduled_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=8, minute=30),
        args=["아침"],
        id="morning_report"
    )
    scheduler.add_job(
        run_scheduled_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=12, minute=30),
        args=["점심"],
        id="lunch_report"
    )
    scheduler.add_job(
        run_scheduled_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=18, minute=30),
        args=["저녁"],
        id="evening_report"
    )
    
    # Weekly cleanup job (Sunday night) to clear database old logs
    scheduler.add_job(
        database.clear_old_alerts,
        trigger=CronTrigger(day_of_week="sun", hour=23, minute=0),
        args=[7],
        id="db_cleanup"
    )
    
    scheduler.start()
    logger.info("Scheduler started successfully with jobs: Morning (08:30), Lunch (12:30), Evening (18:30)")
    return scheduler
