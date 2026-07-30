import google.generativeai as genai
import json
import logging
from config import GEMINI_API_KEY

logger = logging.getLogger("AlimBot.LLMHelper")

# Configure Gemini API if key is available
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logger.warning("GEMINI_API_KEY is not configured. LLM functions will fall back to dummy/mock summaries.")

def resolve_ticker_with_llm(query):
    """
    Uses Gemini API to resolve a Korean or informal stock name to its Yahoo Finance ticker symbol.
    """
    if not GEMINI_API_KEY:
        return None
    try:
        prompt = f"""
너는 금융 데이터베이스봇이다. 사용자가 입력한 한국어 또는 영어 주식/ETF/펀드 명칭을 보고, Yahoo Finance에서 조회 가능한 가장 정확한 티커 심볼(Ticker Symbol, 예: 005930.KS, 005380.KS, AAPL, 069500.KS 등)을 찾아줘.
반드시 아래 JSON 형식으로만 응답해줘. 다른 설명이나 텍스트는 절대 포함하지 마.

질의: {query}

[출력 형식]
{{
  "ticker": "005930.KS",
  "name": "Samsung Electronics Co., Ltd.",
  "type": "STOCK"
}}
"""
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        data = json.loads(response.text.strip())
        if data and data.get("ticker"):
            return {
                "ticker": data["ticker"],
                "name": data.get("name", query),
                "type": data.get("type", "STOCK"),
                "exchange": "KRX" if data["ticker"].endswith((".KS", ".KQ")) else "US"
            }
        return None
    except Exception as e:
        logger.error(f"Error resolving ticker with LLM: {e}")
        return None

def summarize_stock_data(quote, disclosures, news):
    """
    Uses Gemini API to analyze current quote, DART disclosures, and recent news.
    Returns a dictionary with importance, sentiment, and summaries.
    """
    # If API key is not configured, return a basic fallback summary
    if not GEMINI_API_KEY:
        return get_mock_summary(quote, disclosures, news)
        
    try:
        # Format the input data for the LLM
        input_data = {
            "stock_name": quote["name"] if quote else "알 수 없음",
            "ticker": quote["ticker"] if quote else "알 수 없음",
            "current_price": f"{quote['price']:,} {quote['currency']}" if quote else "N/A",
            "price_change": f"{quote['change']:,} ({quote['pct_change']:.2f}%)" if quote else "N/A",
            "disclosures": [{"title": d["title"], "source": d["source"]} for d in disclosures],
            "news": [{"title": n["title"], "source": n["source"]} for n in news]
        }
        
        prompt = f"""
당신은 금융 분석가 인공지능입니다. 제공된 주식/ETF/펀드 데이터(현재가, 전일비 변동률, 공시 목록, 관련 뉴스 제목 목록)를 기반으로 해당 종목의 현재 상태를 분석하고 요약 리포트를 한국어로 작성해 주세요.

[제공된 데이터]
{json.dumps(input_data, ensure_ascii=False, indent=2)}

[요구사항]
1. 뉴스와 공시 정보를 종합하여 중복되거나 무의미한 정보는 제외하고 중요 사항을 선별합니다.
2. 중요도(importance_score)를 1부터 5까지의 정수로 평가해 주세요.
   - 5: 매우 중요 (예: 대규모 합병, 거래정지, 30% 이상 급등락, 중대 법적 분쟁 등)
   - 4: 중요 (예: 실적 발표, 주요 계약 체결, 10% 이상 급등락 등)
   - 3: 보통 (예: 일반적인 시장 뉴스, 3% 이상 급등락 등)
   - 2: 낮음 (예: 일반 변동, 미미한 이슈 등)
   - 1: 아주 낮음 (예: 단순 시황 언급, 특이사항 없음)
3. 해당 종목의 전반적인 분위기를 감성(sentiment)으로 분류해 주세요: "Positive" (호재/상승), "Neutral" (보통/횡보), "Negative" (악재/하락) 중 하나.
4. **텔레그램용 요약(summary_telegram)**:
   - 1~2문장의 핵심만 요약한 간결하고 전달력 높은 문장으로 작성해 주세요. (마크다운 포맷 가능)
5. **이메일용 상세 요약(summary_email)**:
   - 관련 뉴스 및 공시 내용을 기반으로 심층 분석한 리포트를 작성해 주세요. 개조식(Bullet points) 형태로 3~4개의 핵심 내용을 설명해 주세요.

출력 포맷은 반드시 아래 예시와 같은 JSON 형식이어야 합니다. 마크다운 코드 블록(예: ```json ... ```)을 제외한 순수 JSON만 반환하거나 해당 마크다운으로 감싸 반환해 주세요.

[출력 예시]
{{
  "importance_score": 4,
  "sentiment": "Positive",
  "summary_telegram": "금일 삼성전자는 2분기 어닝서프라이즈 발표와 반도체 수출 호조 뉴스로 4.2% 상승했습니다.",
  "summary_email": "- 2분기 영업이익이 전년 동기 대비 15% 증가하여 시장 전망치를 상회하는 어닝 서프라이즈를 기록했습니다.\\n- 고대역폭 메모리(HBM) 신규 공급 계약 체결로 하반기 실적 모멘텀이 강화될 것으로 보입니다.\\n- 외국인과 기관의 강력한 순매수세 유입으로 종가 기준 전일 대비 4.2% 상승 마감하였습니다."
}}
"""

        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        
        # Parse the JSON response
        result = json.loads(response.text.strip())
        return result
        
    except Exception as e:
        logger.error(f"Error in LLM summarization: {e}")
        return get_mock_summary(quote, disclosures, news)

def get_mock_summary(quote, disclosures, news):
    """
    Fallback function when Gemini API is unavailable or fails.
    """
    name = quote["name"] if quote else "알 수 없음"
    pct_change = quote["pct_change"] if quote else 0.0
    price_str = f"{quote['price']:,} {quote['currency']}" if quote else "N/A"
    change_str = f"{quote['change']:,} ({pct_change:.2f}%)" if quote else "N/A"
    
    sentiment = "Neutral"
    if pct_change > 1.5:
        sentiment = "Positive"
    elif pct_change < -1.5:
        sentiment = "Negative"
        
    telegram = f"금일 {name}은(는) {price_str}에 거래 중이며 전일 대비 {change_str} 변동했습니다."
    
    email_bullets = []
    if disclosures:
        email_bullets.append(f"최근 공시: {disclosures[0]['title']} ({disclosures[0]['source']})")
    if news:
        email_bullets.append(f"최근 뉴스: {news[0]['title']} ({news[0]['source']})")
    if not email_bullets:
        email_bullets.append("최근 특이사항이 없습니다.")
        
    email_str = "\n".join([f"- {item}" for item in email_bullets])
    
    return {
        "importance_score": 3 if (disclosures or news) else 2,
        "sentiment": sentiment,
        "summary_telegram": telegram,
        "summary_email": email_str
    }

