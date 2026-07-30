import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from jinja2 import Template
import logging
from datetime import datetime
import config

logger = logging.getLogger("AlimBot.Notifier")

def send_telegram_message(chat_id, text, parse_mode="HTML"):
    """
    Sends a message to the specified Telegram Chat ID.
    Uses requests for synchronous simplicity across scheduler threads.
    """
    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not configured. Cannot send Telegram message.")
        return False
        
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    
    try:
        res = requests.post(url, json=payload, timeout=10)
        res.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Failed to send Telegram message to {chat_id}: {e}")
        return False

# Modern HTML Email Template with CSS
EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>지능형 금융 모니터링 리포트</title>
    <style>
        body {
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            background-color: #f8f9fa;
            color: #333333;
            margin: 0;
            padding: 0;
            -webkit-font-smoothing: antialiased;
        }
        .container {
            max-width: 600px;
            margin: 20px auto;
            background: #ffffff;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 15px rgba(0,0,0,0.05);
            border: 1px solid #e9ecef;
        }
        .header {
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            color: #ffffff;
            padding: 30px 20px;
            text-align: center;
        }
        .header h1 {
            margin: 0;
            font-size: 24px;
            font-weight: 700;
            letter-spacing: -0.5px;
        }
        .header p {
            margin: 5px 0 0 0;
            font-size: 14px;
            opacity: 0.8;
        }
        .content {
            padding: 25px;
        }
        .stock-card {
            background: #ffffff;
            border: 1px solid #e9ecef;
            border-radius: 8px;
            padding: 18px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.02);
        }
        .stock-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #f1f3f5;
            padding-bottom: 10px;
            margin-bottom: 12px;
        }
        .stock-name {
            font-size: 18px;
            font-weight: 700;
            color: #1e3c72;
        }
        .stock-ticker {
            font-size: 12px;
            color: #868e96;
            background: #f1f3f5;
            padding: 2px 6px;
            border-radius: 4px;
            margin-left: 6px;
        }
        .badge {
            font-size: 11px;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 20px;
            text-transform: uppercase;
        }
        .badge-positive { background-color: #d4edda; color: #155724; }
        .badge-negative { background-color: #f8d7da; color: #721c24; }
        .badge-neutral { background-color: #e2e3e5; color: #383d41; }
        
        .stock-price-info {
            display: flex;
            margin-bottom: 15px;
        }
        .price-item {
            flex: 1;
        }
        .price-label {
            font-size: 11px;
            color: #868e96;
            text-transform: uppercase;
            margin-bottom: 4px;
        }
        .price-value {
            font-size: 18px;
            font-weight: 700;
        }
        .up-color { color: #dc3545; }
        .down-color { color: #0d6efd; }
        
        .summary-section {
            background-color: #f8f9fa;
            border-radius: 6px;
            padding: 12px 15px;
            font-size: 13.5px;
            line-height: 1.6;
        }
        .summary-title {
            font-weight: 700;
            color: #495057;
            margin-bottom: 6px;
            font-size: 12px;
            text-transform: uppercase;
        }
        .summary-list {
            margin: 0;
            padding-left: 20px;
        }
        .summary-list li {
            margin-bottom: 6px;
        }
        .footer {
            background-color: #f1f3f5;
            padding: 20px;
            text-align: center;
            font-size: 12px;
            color: #868e96;
            border-top: 1px solid #e9ecef;
        }
        .footer a {
            color: #1e3c72;
            text-decoration: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>지능형 금융 모니터링 리포트</h1>
            <p>발송 시각: {{ timestamp }}</p>
        </div>
        
        <div class="content">
            {% for item in summaries %}
            <div class="stock-card">
                <div class="stock-header">
                    <div>
                        <span class="stock-name">{{ item.name }}</span>
                        <span class="stock-ticker">{{ item.ticker }}</span>
                    </div>
                    <div>
                        {% if item.sentiment == 'Positive' %}
                        <span class="badge badge-positive">호재</span>
                        {% elif item.sentiment == 'Negative' %}
                        <span class="badge badge-negative">악재</span>
                        {% else %}
                        <span class="badge badge-neutral">보통</span>
                        {% endif %}
                    </div>
                </div>
                
                <div class="stock-price-info">
                    <div class="price-item">
                        <div class="price-label">현재가</div>
                        <div class="price-value">{{ "{:,.0f}".format(item.price) if item.currency == 'KRW' else "{:,.2f}".format(item.price) }} {{ item.currency }}</div>
                    </div>
                    <div class="price-item">
                        <div class="price-label">전일대비</div>
                        <div class="price-value {% if item.change > 0 %}up-color{% elif item.change < 0 %}down-color{% endif %}">
                            {% if item.change > 0 %}+{% endif %}{{ "{:,.0f}".format(item.change) if item.currency == 'KRW' else "{:,.2f}".format(item.change) }}
                        </div>
                    </div>
                    <div class="price-item">
                        <div class="price-label">등락률</div>
                        <div class="price-value {% if item.change > 0 %}up-color{% elif item.change < 0 %}down-color{% endif %}">
                            {% if item.change > 0 %}+{% endif %}{{ "{:.2f}".format(item.pct_change) }}%
                        </div>
                    </div>
                </div>
                
                <div class="summary-section">
                    <div class="summary-title">AI 요약 분석</div>
                    <ul class="summary-list">
                        {% for line in item.summary_lines %}
                        <li>{{ line }}</li>
                        {% endfor %}
                    </ul>
                </div>
            </div>
            {% endfor %}
        </div>
        
        <div class="footer">
            본 메일은 사용자가 설정한 정기 알림 주기에 따라 자동으로 발송되었습니다.<br>
            수신 거부 및 종목 설정을 원하시면 텔레그램 봇을 이용해 주세요.
        </div>
    </div>
</body>
</html>
"""

def send_email_report(to_email, summaries):
    """
    Renders and sends HTML report to the specified email using SMTP settings.
    """
    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        logger.error("SMTP credentials not configured. Cannot send email report.")
        return False
        
    try:
        # Pre-process summaries to convert multiline string summary_email into a list of lines
        processed_summaries = []
        for s in summaries:
            summary_str = s.get("summary_email", "")
            # Split and clean lines
            lines = [line.strip().lstrip("-* ").strip() for line in summary_str.split("\n") if line.strip()]
            if not lines:
                lines = ["특이사항이 없습니다."]
                
            processed_summaries.append({
                "name": s["name"],
                "ticker": s["ticker"],
                "price": s.get("price", 0.0),
                "change": s.get("change", 0.0),
                "pct_change": s.get("pct_change", 0.0),
                "currency": s.get("currency", "KRW"),
                "sentiment": s.get("sentiment", "Neutral"),
                "summary_lines": lines
            })
            
        # Render template
        template = Template(EMAIL_TEMPLATE)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        html_content = template.render(summaries=processed_summaries, timestamp=now_str)
        
        # Prepare message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[AlimBot] 지능형 금융 모니터링 리포트 ({now_str})"
        msg["From"] = config.SENDER_EMAIL
        msg["To"] = to_email
        
        msg.attach(MIMEText(html_content, "html"))
        
        # Connect to server and send
        logger.info(f"Connecting to SMTP server {config.SMTP_SERVER}:{config.SMTP_PORT}...")
        server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
        server.starttls()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.sendmail(config.SENDER_EMAIL, to_email, msg.as_string())
        server.quit()
        
        logger.info(f"Successfully sent email report to {to_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email report to {to_email}: {e}")
        return False
