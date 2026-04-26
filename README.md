# 📊 Daily Market Brief

매일 오전 9시(KST)에 시장 데이터와 뉴스를 모아 텔레그램으로 보내고, 웹 대시보드에 게시합니다.

## 구성

- `fetch_market.py` — 데이터 수집 + 텔레그램 발송 + JSON 저장
- `market_dashboard.py` — 로컬 Flask 대시보드 (포트 5051)
- `docs/index.html` — GitHub Pages 정적 대시보드 (휴대폰에서 접속)
- `docs/data/` — 일자별 JSON 스냅샷
- `.github/workflows/daily.yml` — 매일 9시(KST) 자동 실행 + 커밋

## 수집 항목

- **지수**: 코스피, 코스닥, 나스닥, S&P 500, VIX, 미국 10Y, 달러인덱스, WTI, 금
- **환율**: USD/KRW, JPY/KRW, EUR/KRW
- **암호화폐**: BTC, ETH (USD + 업비트 KRW)
- **국내 주식**: 삼성전자, SK하이닉스, 두산에너빌리티, 파마리서치, 한화에어로스페이스
- **해외 주식**: Google, Meta, Tesla, Nvidia, Micron
- **뉴스**: 한경, 매경, 인포맥스, Yahoo Finance, CNBC

## 로컬 실행

```bash
pip install -r requirements.txt

# 데이터 수집 + 텔레그램 발송 (한 번)
TELEGRAM_BOT_TOKEN="..." TELEGRAM_CHAT_ID="..." python3 fetch_market.py

# 대시보드 (브라우저: http://localhost:5051)
python3 market_dashboard.py
```

## GitHub Actions 환경변수

repo Settings → Secrets and variables → Actions:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
