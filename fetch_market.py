"""
매일 오전 9시(KST)에 실행되는 시장 데이터 수집 스크립트.
- yfinance로 지수/환율/주식/코인(USD) 시세 수집
- 업비트 API로 BTC/ETH 원화 시세
- RSS로 뉴스 수집
- 텔레그램으로 요약 발송
- data/latest.json + data/YYYY-MM-DD.json 저장 (대시보드가 읽음)

환경변수:
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
"""
from __future__ import annotations
import os, sys, json, time, html
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
import feedparser
import yfinance as yf

KST = timezone(timedelta(hours=9))
DATA_DIR = Path(__file__).parent / "docs" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---- 수집 대상 ----
INDICES = [
    ("코스피",   "^KS11",  "KRW"),
    ("코스닥",   "^KQ11",  "KRW"),
    ("나스닥",   "^IXIC",  "USD"),
    ("S&P 500", "^GSPC",  "USD"),
    ("VIX",     "^VIX",   ""),
    ("미국 10Y","^TNX",   "%"),
    ("달러인덱스","DX-Y.NYB",""),
    ("WTI 유가","CL=F",   "USD"),
    ("금",      "GC=F",   "USD"),
]

FX = [
    ("USD/KRW", "KRW=X"),
    ("JPY/KRW", "JPYKRW=X"),
    ("EUR/KRW", "EURKRW=X"),
]

STOCKS_KR = [
    ("삼성전자",       "005930.KS"),
    ("SK하이닉스",     "000660.KS"),
    ("두산에너빌리티", "034020.KS"),
    ("파마리서치",     "214450.KQ"),
    ("한화에어로스페이스","012450.KS"),
]

STOCKS_US = [
    ("Google (Alphabet)", "GOOGL"),
    ("Meta",              "META"),
    ("Tesla",             "TSLA"),
    ("Nvidia",            "NVDA"),
    ("Micron",            "MU"),
]
# X-energy는 비상장 (2026.04 기준 IPO 전). 상장되면 티커 추가.
UNLISTED_NOTE = ["X-energy (비상장)"]

CRYPTO_USD = [
    ("Bitcoin",  "BTC-USD", "KRW-BTC"),
    ("Ethereum", "ETH-USD", "KRW-ETH"),
]

NEWS_FEEDS = [
    ("한국경제 증권",   "https://www.hankyung.com/feed/finance"),
    ("매일경제 증권",   "https://www.mk.co.kr/rss/30000023/"),
    ("연합인포맥스",    "https://news.einfomax.co.kr/rss/allArticle.xml"),
    ("Yahoo Finance",  "https://finance.yahoo.com/news/rssindex"),
    ("CNBC Top News",  "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
]

# ----------------------------------------------------------------------------

def _fetch_yf_quotes(symbols: list[str]) -> dict[str, dict]:
    """yfinance로 여러 심볼의 최근 2거래일 종가를 가져와 가격/등락 계산."""
    out: dict[str, dict] = {}
    if not symbols:
        return out
    try:
        df = yf.download(
            tickers=" ".join(symbols),
            period="5d",
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
    except Exception as e:
        print(f"[yf.download] error: {e}", file=sys.stderr)
        return out

    for sym in symbols:
        try:
            if len(symbols) == 1:
                close = df["Close"].dropna()
            else:
                close = df[sym]["Close"].dropna()
            if len(close) < 1:
                continue
            price = float(close.iloc[-1])
            prev = float(close.iloc[-2]) if len(close) >= 2 else price
            change = price - prev
            pct = (change / prev * 100) if prev else 0.0
            out[sym] = {"price": price, "prev": prev, "change": change, "change_pct": pct}
        except Exception as e:
            print(f"[yf parse] {sym}: {e}", file=sys.stderr)

    # 누락된 심볼은 개별 재시도 (캐시 lock 등으로 묶음 다운로드가 실패할 수 있음)
    missing = [s for s in symbols if s not in out]
    for sym in missing:
        try:
            hist = yf.Ticker(sym).history(period="5d", interval="1d", auto_adjust=False)
            close = hist["Close"].dropna()
            if len(close) < 1:
                continue
            price = float(close.iloc[-1])
            prev = float(close.iloc[-2]) if len(close) >= 2 else price
            change = price - prev
            pct = (change / prev * 100) if prev else 0.0
            out[sym] = {"price": price, "prev": prev, "change": change, "change_pct": pct}
        except Exception as e:
            print(f"[yf retry] {sym}: {e}", file=sys.stderr)
    return out


def _fetch_upbit(market: str) -> dict | None:
    """업비트 시세 (원화)."""
    try:
        r = requests.get(
            "https://api.upbit.com/v1/ticker",
            params={"markets": market},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()[0]
        return {
            "price": float(data["trade_price"]),
            "change_pct": float(data["signed_change_rate"]) * 100,
            "change": float(data["signed_change_price"]),
        }
    except Exception as e:
        print(f"[upbit] {market}: {e}", file=sys.stderr)
        return None


def _fetch_news(max_per_feed: int = 4, max_total: int = 20) -> list[dict]:
    items: list[dict] = []
    for source, url in NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                items.append({
                    "source": source,
                    "title": entry.get("title", "").strip(),
                    "url": entry.get("link", ""),
                    "published": entry.get("published", "") or entry.get("updated", ""),
                })
        except Exception as e:
            print(f"[news] {source}: {e}", file=sys.stderr)
    return items[:max_total]


def collect() -> dict:
    """전체 시장 데이터를 모아 dict 리턴."""
    all_symbols = (
        [s for _, s, _ in INDICES]
        + [s for _, s in FX]
        + [s for _, s in STOCKS_KR]
        + [s for _, s in STOCKS_US]
        + [s for _, s, _ in CRYPTO_USD]
    )
    quotes = _fetch_yf_quotes(all_symbols)

    def pack(name, sym, **extra):
        q = quotes.get(sym, {})
        return {"name": name, "symbol": sym, **q, **extra}

    indices = [pack(n, s, unit=u) for n, s, u in INDICES]
    fx = [pack(n, s) for n, s in FX]
    stocks_kr = [pack(n, s, currency="KRW") for n, s in STOCKS_KR]
    stocks_us = [pack(n, s, currency="USD") for n, s in STOCKS_US]

    crypto = []
    for name, yfsym, upbit_market in CRYPTO_USD:
        usd = quotes.get(yfsym, {})
        krw = _fetch_upbit(upbit_market) or {}
        crypto.append({
            "name": name,
            "usd": usd.get("price"),
            "usd_change_pct": usd.get("change_pct"),
            "krw": krw.get("price"),
            "krw_change_pct": krw.get("change_pct"),
        })

    news = _fetch_news()

    return {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "indices": indices,
        "fx": fx,
        "stocks_kr": stocks_kr,
        "stocks_us": stocks_us,
        "stocks_unlisted": UNLISTED_NOTE,
        "crypto": crypto,
        "news": news,
    }


# ---- 텔레그램 ----

def _fmt_price(v, decimals=2):
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:,.{decimals}f}"

def _fmt_pct(v):
    if v is None:
        return "—"
    arrow = "▲" if v > 0 else ("▼" if v < 0 else "·")
    return f"{arrow}{abs(v):.2f}%"

def _line(name, price, pct, decimals=2):
    return f"<b>{html.escape(name)}</b>  {_fmt_price(price, decimals)}  ({_fmt_pct(pct)})"

def build_telegram_message(d: dict) -> str:
    ts = d["generated_at"][:16].replace("T", " ")
    parts = [f"📊 <b>아침 시장 브리핑</b>  <i>{ts} KST</i>", ""]

    parts.append("📈 <b>주요 지수</b>")
    for x in d["indices"]:
        parts.append("  " + _line(x["name"], x.get("price"), x.get("change_pct")))
    parts.append("")

    parts.append("💱 <b>환율</b>")
    for x in d["fx"]:
        parts.append("  " + _line(x["name"], x.get("price"), x.get("change_pct")))
    parts.append("")

    parts.append("₿ <b>암호화폐</b>")
    for x in d["crypto"]:
        usd = _fmt_price(x.get("usd"))
        krw = _fmt_price(x.get("krw"))
        usdpct = _fmt_pct(x.get("usd_change_pct"))
        krwpct = _fmt_pct(x.get("krw_change_pct"))
        parts.append(f"  <b>{x['name']}</b>  ${usd} ({usdpct}) / ₩{krw} ({krwpct})")
    parts.append("")

    parts.append("🇰🇷 <b>국내 주식</b>")
    for x in d["stocks_kr"]:
        parts.append("  " + _line(x["name"], x.get("price"), x.get("change_pct"), decimals=0))
    parts.append("")

    parts.append("🇺🇸 <b>해외 주식</b>")
    for x in d["stocks_us"]:
        parts.append("  " + _line(x["name"], x.get("price"), x.get("change_pct")))
    for note in d.get("stocks_unlisted", []):
        parts.append(f"  <i>{html.escape(note)}</i>")
    parts.append("")

    parts.append("📰 <b>주요 뉴스</b>")
    for n in d["news"][:8]:
        title = html.escape(n["title"])[:80]
        url = html.escape(n["url"])
        src = html.escape(n["source"])
        parts.append(f'  · <a href="{url}">{title}</a> <i>[{src}]</i>')

    return "\n".join(parts)


def send_telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[telegram] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정", file=sys.stderr)
        return False
    # 4096자 제한
    chunks = [text[i:i+3900] for i in range(0, len(text), 3900)]
    ok = True
    for chunk in chunks:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            },
            timeout=15,
        )
        if not r.ok:
            print(f"[telegram] send failed: {r.status_code} {r.text}", file=sys.stderr)
            ok = False
    return ok


def save(d: dict):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    (DATA_DIR / f"{today}.json").write_text(
        json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA_DIR / "latest.json").write_text(
        json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    print(f"=== 시장 데이터 수집 시작: {datetime.now(KST).isoformat()} ===")
    data = collect()
    save(data)
    print(f"  지수 {len(data['indices'])}, 환율 {len(data['fx'])}, "
          f"국내주식 {len(data['stocks_kr'])}, 해외주식 {len(data['stocks_us'])}, "
          f"코인 {len(data['crypto'])}, 뉴스 {len(data['news'])}")
    msg = build_telegram_message(data)
    sent = send_telegram(msg)
    print(f"  텔레그램 발송: {'성공' if sent else '실패/스킵'}")
    print("=== 완료 ===")


if __name__ == "__main__":
    main()
