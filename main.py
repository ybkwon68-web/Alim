import sys
import logging
import asyncio
import config
import database
import scheduler
import bot

# Configure Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("alim_bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("AlimBot.Main")

def main():
    logger.info("Starting AlimBot...")
    
    # 1. Check Configuration
    config.check_config()
    
    # 2. Initialize Database
    database.init_db()
    
    # 3. Start Background Scheduler
    sched = scheduler.start_scheduler()
    
    # 3.5 Start Web Dashboard Server (in a background daemon thread)
    from threading import Thread
    from web_server import app as web_app
    
    def run_web_server():
        logger.info("Starting Web Dashboard on http://localhost:58291...")
        web_app.run(host="0.0.0.0", port=58291, use_reloader=False)
        
    web_thread = Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    # 4. Build and Run Telegram Bot
    telegram_app = bot.build_application()
    
    if telegram_app is None:
        logger.error("Failed to build Telegram Application due to missing token. Exiting.")
        sys.exit(1)
        
    logger.info("Telegram Bot is starting polling...")
    try:
        # run_polling is blocking and handles asyncio internally
        telegram_app.run_polling()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Stopping bot...")
    except Exception as e:
        logger.error(f"Unexpected error running bot: {e}")
    finally:
        logger.info("Stopping scheduler...")
        sched.shutdown()
        logger.info("AlimBot stopped.")

if __name__ == "__main__":
    main()
