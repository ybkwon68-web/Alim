import re
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import database
import collector
import llm_helper
import notifier
import config

logger = logging.getLogger("AlimBot.Bot")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    database.add_user(chat_id)
    
    welcome_text = (
        "🤖 <b>지능형 주식/ETF 모니터링 알림 봇</b>\n\n"
        "이 봇은 관심 종목의 시세, 뉴스, 공시를 모니터링하고 정기적인 리포트를 제공합니다.\n\n"
        "<b>주요 명령어 안내:</b>\n"
        "📌 <b>설정 및 관리</b>\n"
        "• /email <code>[이메일주소]</code> - 상세 리포트를 받아볼 이메일 등록\n"
        "• /add <code>[종목명 또는 코드]</code> - 관심 종목 등록 (예: <code>/add 삼성전자</code> 또는 <code>/add AAPL</code>)\n"
        "• /delete <code>[종목명 또는 티커]</code> - 관심 종목 삭제\n"
        "• /list - 현재 등록된 관심 종목 확인\n\n"
        "📊 <b>실시간 조회 및 발송</b>\n"
        "• /price <code>[종목명/티커]</code> - 실시간 시세 조회 (입력하지 않으면 등록된 모든 종목 조회)\n"
        "• /summary - 현재 등록된 관심 종목에 대한 실시간 AI 요약 브리핑\n"
        "• /sendmail - 등록된 이메일로 심층 분석 리포트 즉시 발송"
    )
    await update.message.reply_html(welcome_text)

async def register_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_html("⚠️ 사용법: <code>/email [이메일주소]</code>\n예: <code>/email user@example.com</code>")
        return
        
    email = context.args[0].strip()
    # Simple email validation
    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        await update.message.reply_text("⚠️ 올바른 이메일 형식이 아닙니다.")
        return
        
    if database.update_user_email(chat_id, email):
        await update.message.reply_html(f"✅ 이메일 주소가 <b>{email}</b>(으)로 등록되었습니다. 이제 상세 리포트를 메일로 받으실 수 있습니다.")
    else:
        await update.message.reply_text("❌ 이메일 등록 중 오류가 발생했습니다.")

async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_html("⚠️ 사용법: <code>/add [종목명 또는 티커]</code>\n예: <code>/add 삼성전자</code> 또는 <code>/add 005930</code>")
        return
        
    query = " ".join(context.args).strip()
    await update.message.reply_text(f"🔍 '{query}' 종목을 검색 중입니다...")
    
    candidates = collector.resolve_stock(query)
    if not candidates:
        await update.message.reply_text("❌ 일치하는 종목을 찾지 못했습니다. 종목명이나 티커를 다시 확인해 주세요.")
        return
        
    # Pick the first candidate
    best_match = candidates[0]
    ticker = best_match["ticker"]
    name = best_match["name"]
    stock_type = best_match["type"]
    
    # Save to Database
    if database.add_stock(chat_id, ticker, name, stock_type):
        reply_msg = f"✅ <b>{name}</b> ({ticker}) 종목이 관심 종목으로 등록되었습니다.\n"
        if len(candidates) > 1:
            reply_msg += "\n💡 <b>다른 검색 결과:</b>\n"
            for cand in candidates[1:4]:
                reply_msg += f"- <code>/add {cand['ticker']}</code> ({cand['name']})\n"
        await update.message.reply_html(reply_msg)
    else:
        await update.message.reply_text("❌ 관심 종목 등록에 실패했습니다. (이미 등록된 종목일 수 있습니다)")

async def remove_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_html("⚠️ 사용법: <code>/delete [종목명 또는 티커]</code>\n예: <code>/delete 삼성전자</code> 또는 <code>/delete 005930.KS</code>")
        return
        
    query = " ".join(context.args).strip()
    if database.remove_stock(chat_id, query):
        await update.message.reply_html(f"✅ <b>{query}</b> 관련 종목이 관심 목록에서 삭제되었습니다.")
    else:
        await update.message.reply_text("❌ 관심 목록에서 해당 종목을 찾지 못했습니다.")

async def list_stocks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    stocks = database.get_user_stocks(chat_id)
    
    if not stocks:
        await update.message.reply_html("⚠️ 현재 등록된 관심 종목이 없습니다. <code>/add [종목명]</code> 명령어로 추가해 보세요.")
        return
        
    msg = "📋 <b>나의 관심 종목 목록:</b>\n\n"
    for i, stock in enumerate(stocks, 1):
        msg += f"{i}. <b>{stock['name']}</b> ({stock['ticker']}) - [{stock['type']}]\n"
    await update.message.reply_html(msg)

async def current_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    # Check if querying specific stock or all registered
    if context.args:
        query = " ".join(context.args).strip()
        candidates = collector.resolve_stock(query)
        if not candidates:
            await update.message.reply_text("❌ 일치하는 종목을 찾을 수 없습니다.")
            return
        tickers_to_fetch = [(cand["ticker"], cand["name"]) for cand in candidates[:1]]
    else:
        stocks = database.get_user_stocks(chat_id)
        if not stocks:
            await update.message.reply_html("⚠️ 등록된 관심 종목이 없습니다. <code>/price [종목명]</code>으로 개별 검색해 보세요.")
            return
        tickers_to_fetch = [(s["ticker"], s["name"]) for s in stocks]
        
    await update.message.reply_text("📊 실시간 시세를 수집하고 있습니다...")
    
    msg = "📈 <b>실시간 시세 정보:</b>\n\n"
    for ticker, name in tickers_to_fetch:
        quote = collector.fetch_stock_quote(ticker)
        if not quote:
            # Try fund fetch
            quote = collector.fetch_fund_price(ticker)
            
        if quote:
            sign = "+" if quote["change"] > 0 else ""
            color = "🔴" if quote["change"] > 0 else ("🔵" if quote["change"] < 0 else "⚪")
            price_formatted = f"{quote['price']:,}" if quote['currency'] == 'KRW' else f"{quote['price']:.2f}"
            change_formatted = f"{quote['change']:,}" if quote['currency'] == 'KRW' else f"{quote['change']:.2f}"
            
            msg += (
                f"{color} <b>{quote['name']}</b> ({quote['ticker']})\n"
                f"• 현재가: {price_formatted} {quote['currency']}\n"
                f"• 전일비: {sign}{change_formatted} ({sign}{quote['pct_change']:.2f}%)\n"
                f"• 고가/저가: {quote['high']:,} / {quote['low']:,}\n\n"
            )
        else:
            msg += f"❌ <b>{name}</b> ({ticker}) 시세 정보를 불러올 수 없습니다.\n\n"
            
    await update.message.reply_html(msg)

async def summarize_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    stocks = database.get_user_stocks(chat_id)
    
    if not stocks:
        await update.message.reply_html("⚠️ 등록된 관심 종목이 없습니다. 먼저 종목을 추가해 주세요.")
        return
        
    await update.message.reply_text("🤖 관심 종목에 대한 실시간 뉴스 및 공시를 수집하여 AI 브리핑을 작성하고 있습니다. 잠시만 기다려 주세요 (약 10~15초 소요)...")
    
    summaries_text = "🤖 <b>관심 종목 실시간 AI 브리핑</b>\n\n"
    
    for stock in stocks:
        ticker = stock["ticker"]
        name = stock["name"]
        
        # 1. Fetch Quote
        quote = collector.fetch_stock_quote(ticker) or collector.fetch_fund_price(ticker)
        if not quote:
            continue
            
        # 2. Fetch Disclosures & News (last 24 hours for on-demand)
        disclosures = collector.fetch_dart_disclosures(ticker, hours=24)
        news = collector.fetch_stock_news(name, ticker, hours=24)
        
        # 3. Get LLM Summary
        summary_res = llm_helper.summarize_stock_data(quote, disclosures, news)
        
        # Format text
        sign = "+" if quote["change"] > 0 else ""
        color = "🔴" if quote["change"] > 0 else ("🔵" if quote["change"] < 0 else "⚪")
        price_formatted = f"{quote['price']:,}" if quote['currency'] == 'KRW' else f"{quote['price']:.2f}"
        
        summaries_text += (
            f"{color} <b>{name}</b> ({ticker})\n"
            f"• 시세: {price_formatted} {quote['currency']} ({sign}{quote['pct_change']:.2f}%)\n"
            f"• 요약: {summary_res.get('summary_telegram')}\n\n"
        )
        
    await update.message.reply_html(summaries_text)

async def mail_report_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = database.get_user(chat_id)
    
    if not user or not user["email"]:
        await update.message.reply_html("⚠️ 등록된 이메일이 없습니다. 먼저 <code>/email [이메일주소]</code> 명령어로 등록해 주세요.")
        return
        
    stocks = database.get_user_stocks(chat_id)
    if not stocks:
        await update.message.reply_html("⚠️ 등록된 관심 종목이 없습니다. 먼저 종목을 추가해 주세요.")
        return
        
    email_address = user["email"]
    await update.message.reply_html(f"✉️ <b>{email_address}</b>(으)로 심층 분석 리포트를 작성하여 발송하고 있습니다. 잠시만 기다려 주세요...")
    
    summaries = []
    for stock in stocks:
        ticker = stock["ticker"]
        name = stock["name"]
        
        quote = collector.fetch_stock_quote(ticker) or collector.fetch_fund_price(ticker)
        if not quote:
            continue
            
        disclosures = collector.fetch_dart_disclosures(ticker, hours=24)
        news = collector.fetch_stock_news(name, ticker, hours=24)
        
        summary_res = llm_helper.summarize_stock_data(quote, disclosures, news)
        summary_res.update(quote)
        summaries.append(summary_res)
        
    if summaries:
        if notifier.send_email_report(email_address, summaries):
            await update.message.reply_html(f"✅ <b>{email_address}</b>(으)로 리포트 메일이 성공적으로 발송되었습니다.")
        else:
            await update.message.reply_text("❌ 이메일 전송 도중 에러가 발생했습니다. SMTP 설정을 확인해 주세요.")
    else:
        await update.message.reply_text("❌ 수집된 종목 정보가 없어 메일을 발송하지 못했습니다.")

def build_application():
    """
    Builds the Telegram Application instance.
    """
    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing!")
        return None
        
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command))
    application.add_handler(CommandHandler("email", register_email))
    application.add_handler(CommandHandler("add", add_stock))
    application.add_handler(CommandHandler("delete", remove_stock))
    application.add_handler(CommandHandler("list", list_stocks))
    application.add_handler(CommandHandler("price", current_price))
    application.add_handler(CommandHandler("summary", summarize_now))
    application.add_handler(CommandHandler("sendmail", mail_report_now))
    
    return application
