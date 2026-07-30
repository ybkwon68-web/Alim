import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import yfinance as yf
from datetime import datetime, timedelta
import urllib.parse
import logging
import re
from config import DART_API_KEY

logger = logging.getLogger("AlimBot.Collector")

def resolve_stock(query):
    """
    Search Yahoo Finance search API to find stock/ETF tickers matching the query.
    If the query is a 6-digit numeric string, treats it as a Korean stock code and returns matches.
    If the query contains Korean characters, uses LLM helper first.
    """
    query = query.strip()
    
    # Check if Korean 6-digit code
    if re.match(r"^\d{6}$", query):
        # Try both .KS and .KQ
        for suffix in [".KS", ".KQ"]:
            symbol = query + suffix
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                # If we get info and it has a longName/shortName, it's valid
                name = info.get("longName") or info.get("shortName") or symbol
                quote_type = info.get("quoteType", "EQUITY")
                return [{
                    "ticker": symbol,
                    "name": name,
                    "type": quote_type,
                    "exchange": info.get("exchange", "KRX")
                }]
            except Exception:
                continue
                
    # If the query contains Korean characters, try LLM ticker resolution first
    if re.search(r"[ㄱ-ㅎㅏ-ㅣ가-힣]", query):
        try:
            import llm_helper
            llm_result = llm_helper.resolve_ticker_with_llm(query)
            if llm_result:
                logger.info(f"Resolved Korean query '{query}' to ticker '{llm_result['ticker']}' using LLM.")
                return [llm_result]
        except Exception as e:
            logger.error(f"Error resolving Korean query with LLM: {e}")

    # Standard search query via Yahoo Finance search API
    encoded_query = urllib.parse.quote(query)
    url = f"https://query1.finance.yahoo.com/v1/finance/search?q={encoded_query}&quotesCount=5&newsCount=0"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        candidates = []
        for quote in data.get("quotes", []):
            symbol = quote.get("symbol")
            name = quote.get("longname") or quote.get("shortname") or symbol
            quote_type = quote.get("quoteType", "EQUITY")
            exchange = quote.get("exchange", "")
            
            candidates.append({
                "ticker": symbol,
                "name": name,
                "type": quote_type,
                "exchange": exchange
            })
        return candidates
    except Exception as e:
        logger.warning(f"Yahoo search endpoint failed: {e}. Trying fallback yfinance Search.")
        # Fallback to yfinance built-in Search module
        try:
            s = yf.Search(query)
            candidates = []
            for quote in s.quotes:
                symbol = quote.get("symbol")
                name = quote.get("longname") or quote.get("shortname") or symbol
                quote_type = quote.get("quoteType", "EQUITY")
                exchange = quote.get("exchange", "")
                candidates.append({
                    "ticker": symbol,
                    "name": name,
                    "type": quote_type,
                    "exchange": exchange
                })
            return candidates
        except Exception as ex:
            logger.error(f"Fallback yfinance Search also failed: {ex}")
            return []


def fetch_stock_quote(ticker_symbol):
    """
    Fetch current stock price and key metrics using yfinance.
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        # Fetch fast info or history to get latest price
        history = ticker.history(period="2d")
        if history.empty:
            return None
        
        info = ticker.info
        latest_close = history['Close'].iloc[-1]
        prev_close = history['Close'].iloc[0] if len(history) > 1 else latest_close
        
        change = latest_close - prev_close
        pct_change = (change / prev_close) * 100 if prev_close else 0.0
        
        return {
            "ticker": ticker_symbol,
            "name": info.get("longName") or info.get("shortName") or ticker_symbol,
            "price": float(latest_close),
            "change": float(change),
            "pct_change": float(pct_change),
            "open": float(history['Open'].iloc[-1]),
            "high": float(history['High'].iloc[-1]),
            "low": float(history['Low'].iloc[-1]),
            "volume": int(history['Volume'].iloc[-1]),
            "currency": info.get("currency", "KRW")
        }
    except Exception as e:
        logger.error(f"Error fetching quote for {ticker_symbol}: {e}")
        return None

def fetch_dart_disclosures(ticker_symbol, hours=24):
    """
    Fetch DART disclosures for Korean stocks/ETFs.
    Ticker symbol should end with .KS or .KQ (e.g. 005930.KS).
    """
    if not DART_API_KEY:
        logger.warning("DART_API_KEY is not set. Skipping DART disclosures.")
        return []
    
    # Extract 6-digit stock code
    match = re.match(r"^(\d{6})\.(KS|KQ)$", ticker_symbol)
    if not match:
        # DART only supports KRX listed companies with 6-digit codes
        return []
    
    stock_code = match.group(1)
    
    # DART API parameters
    today = datetime.now()
    start_date = (today - timedelta(days=2)).strftime("%Y%m%d")  # Fetch last 2 days to ensure coverage
    end_date = today.strftime("%Y%m%d")
    
    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "stock_code": stock_code,
        "bgn_de": start_date,
        "end_de": end_date,
        "page_no": 1,
        "page_count": 10
    }
    
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        if data.get("status") != "000":
            # "013" status means no data found, which is normal
            if data.get("status") != "013":
                logger.warning(f"DART API return status error: {data.get('message')}")
            return []
            
        disclosures = []
        now = datetime.now()
        for doc in data.get("list", []):
            # Parse receipt date & time (DART 'rcept_dt' is YYYYMMDD, time is not direct, but we can check if it's within range)
            rcept_dt_str = doc.get("rcept_dt")  # YYYYMMDD
            try:
                rcept_date = datetime.strptime(rcept_dt_str, "%Y%m%d")
                # Since DART 'list.json' doesn't give exact hour in the main response, we assume dates matching today/yesterday.
                # To be precise, let's filter if rcept_date is within hours limit.
                delta = now - rcept_date
                if delta.days * 24 > hours:
                    continue
            except Exception:
                pass
                
            rcept_no = doc.get("rcept_no")
            disclosures.append({
                "id": rcept_no,
                "title": doc.get("report_nm"),
                "pub_date": doc.get("rcept_dt"),
                "submitter": doc.get("flr_nm"),
                "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
                "source": "DART"
            })
        return disclosures
    except Exception as e:
        logger.error(f"Error fetching DART disclosures for {ticker_symbol}: {e}")
        return []

def fetch_stock_news(stock_name, ticker_symbol, hours=12):
    """
    Fetch news from Google News RSS for the given stock.
    Filters news matching pub_date within `hours`.
    """
    # Clean stock name for better search query
    clean_name = re.sub(r"\(.*?\)|\[.*?\]", "", stock_name).strip()
    query = f"{clean_name}"
    
    # Fetch from Google News RSS
    encoded_query = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        
        # Parse XML
        root = ET.fromstring(res.content)
        news_items = []
        now = datetime.now()
        
        for item in root.findall(".//item"):
            title = item.find("title").text
            link = item.find("link").text
            pub_date_str = item.find("pubDate").text  # e.g., "Thu, 30 Jul 2026 03:00:00 GMT"
            source = item.find("source").text if item.find("source") is not None else "Google News"
            
            # Parse RFC 822 format date: "Thu, 30 Jul 2026 03:00:00 GMT" or "Thu, 30 Jul 2026 03:00:00 +0000"
            try:
                # Remove timezone name like 'GMT' if any, or offset
                clean_date_str = re.sub(r"\s[A-Z]{3,4}$|\s\+\d{4}$", "", pub_date_str)
                pub_date = datetime.strptime(clean_date_str, "%a, %d %b %Y %H:%M:%S")
                
                # Check if within hour limit
                if (now - pub_date).total_seconds() / 3600.0 > hours:
                    continue
            except Exception as e:
                # If date parsing fails, log it but don't crash
                logger.debug(f"Date parsing failed for '{pub_date_str}': {e}")
                pub_date = now
            
            news_items.append({
                "title": title,
                "url": link,
                "pub_date": pub_date.strftime("%Y-%m-%d %H:%M:%S"),
                "source": source
            })
            
            # Limit to top 10 recent news to avoid LLM overload
            if len(news_items) >= 10:
                break
                
        return news_items
    except Exception as e:
        logger.error(f"Error fetching news for {stock_name}: {e}")
        return []

def fetch_fund_price(fund_code):
    """
    Scrapes Naver Finance fund detail page for mutual funds that are not on yfinance.
    """
    url = f"https://finance.naver.com/fund/fundDetail.naver?fund_cd={fund_code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        
        # Get fund name
        name_tag = soup.select_one(".wrap_fund_name h2")
        name = name_tag.text.strip() if name_tag else fund_code
        
        # Get base price (기준가격)
        price_tag = soup.select_one(".price_today .today .no_today")
        if not price_tag:
            return None
        
        price_text = price_tag.text.strip().replace(",", "")
        price = float(re.findall(r"\d+\.\d+|\d+", price_text)[0])
        
        # Get change
        change_tag = soup.select_one(".price_today .today .no_exday")
        change = 0.0
        pct_change = 0.0
        if change_tag:
            # Find up/down class
            ico = change_tag.select_one(".ico_up, .ico_down")
            sign = 1.0
            if ico and "down" in ico.get("class", []):
                sign = -1.0
            
            change_val_tag = change_tag.select_one(".no_exday") or change_tag
            change_text = change_val_tag.text.strip().split()[0].replace(",", "")
            try:
                change = float(re.findall(r"\d+\.\d+|\d+", change_text)[0]) * sign
            except Exception:
                pass
                
        return {
            "ticker": fund_code,
            "name": name,
            "price": price,
            "change": change,
            "pct_change": (change / (price - change)) * 100 if (price - change) else 0.0,
            "open": price,
            "high": price,
            "low": price,
            "volume": 0,
            "currency": "KRW",
            "type": "FUND"
        }
    except Exception as e:
        logger.error(f"Error fetching fund {fund_code}: {e}")
        return None
