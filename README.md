# market-lens-mcp

한국 주식 리서치용 MCP 서버입니다. Claude Desktop 같은 MCP 클라이언트에 붙이면 상장사의 공시, 재무제표, 주가를 공식 API에서 가져와 출처와 기준일이 붙은 답을 만들 수 있습니다.

투자 권유 도구가 아닙니다. [DISCLAIMER.md](DISCLAIMER.md)를 먼저 읽어 주세요.

## 도구

| 도구 | 입력 | 출력 | 데이터 소스 |
| --- | --- | --- | --- |
| `resolve_ticker` | 종목명 또는 종목코드 | 단축코드, ISIN, DART corp_code, 시장 | KRX상장종목정보 + DART 고유번호 |
| `list_disclosures` | 종목, 기간, 공시유형 | 공시 목록(제목, 접수일, 접수번호) | DART |
| `get_disclosure_text` | 접수번호 | 공시 본문 텍스트(길이 제한, 이어 읽기) | DART |
| `get_financials` | 종목, 연도, 분기 | 매출, 영업이익, 순이익, 자산, 부채, 자본 | DART |
| `get_stock_prices` | 종목, 기간 | 일별 OHLCV | 금융위원회 주식시세정보 |

모든 응답은 같은 형식입니다.

```json
{
  "source": "DART OpenAPI (금융감독원 전자공시시스템)",
  "as_of": "2024-09-30",
  "fetched_at": "2024-11-15T09:12:03+09:00",
  "cached": false,
  "data": { },
  "computed": { "revenue_change_pct": 12.5 },
  "warnings": [],
  "disclaimer": "…"
}
```

- `source`, `as_of`: 출처와 데이터 기준일. 답변에 그대로 인용합니다.
- `computed`: 증감률, 이익률, 부채비율, 기간 수익률처럼 서버가 코드로 계산한 값. 모델이 암산하지 않게 하기 위한 필드입니다.

## 설치

Python 3.11 이상과 [uv](https://docs.astral.sh/uv/)가 필요합니다. MCP Python SDK는 2.x(`MCPServer`)를 씁니다.

```bash
git clone https://github.com/itsdanieldev/market-lens-mcp.git
cd market-lens-mcp
uv sync
cp .env.example .env   # 키 두 개를 채웁니다
```

## 키 발급

둘 다 무료입니다.

**DART_API_KEY**

1. [opendart.fss.or.kr](https://opendart.fss.or.kr)에서 회원가입
2. 인증키 신청/관리 → 인증키 신청
3. 발급된 40자리 키를 `.env`의 `DART_API_KEY`에 입력

**DATA_GO_KR_KEY**

1. [data.go.kr](https://www.data.go.kr)에서 회원가입
2. 아래 두 API에서 각각 "활용신청" (자동승인)
   - [금융위원회_주식시세정보](https://www.data.go.kr/data/15094808/openapi.do)
   - [금융위원회_KRX상장종목정보](https://www.data.go.kr/data/15094775/openapi.do)
3. 마이페이지의 일반 인증키를 `.env`의 `DATA_GO_KR_KEY`에 입력 (Encoding, Decoding 키 모두 됩니다)

승인 직후에는 키가 반영될 때까지 `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`가 날 수 있습니다. 잠시 뒤 다시 시도하세요.

키가 하나만 있어도 일부 도구는 동작합니다. 공시·재무 도구는 DART 키만, `get_stock_prices`는 공공데이터포털 키만 있으면 됩니다.

## Claude Desktop 설정

설정 → 개발자 → 구성 편집으로 `claude_desktop_config.json`을 열고 아래를 추가한 뒤 앱을 다시 시작합니다. 경로는 이 저장소를 받은 절대 경로로 바꿉니다.

```json
{
  "mcpServers": {
    "market-lens": {
      "command": "uv",
      "args": ["--directory", "/절대/경로/market-lens-mcp", "run", "market-lens-mcp"]
    }
  }
}
```

키는 저장소 루트의 `.env`에서 읽습니다. Claude Code에서는 다음 한 줄로 등록합니다.

```bash
claude mcp add market-lens -- uv --directory /절대/경로/market-lens-mcp run market-lens-mcp
```

## 질문 예시

- 삼성전자 최근 실적과 공시 요약해줘
- SK하이닉스 2024년 3분기 영업이익이 전년 동기 대비 얼마나 변했어?
- 카카오 최근 한 달 주요사항보고 공시 목록 보여줘
- 방금 목록의 첫 번째 공시 본문 읽고 핵심만 정리해줘
- 네이버 최근 90일 주가 흐름과 기간 수익률 알려줘

## 캐시

호출 한도를 아끼려고 응답을 SQLite(`~/.cache/market-lens/cache.sqlite3`)에 저장합니다. 위치는 `MARKET_LENS_CACHE_DIR`로 바꿉니다.

| 데이터 | 유효 기간 |
| --- | --- |
| 주가 | 당일(KST 자정까지) |
| 상장종목 목록, DART 고유번호 | 1일 |
| 공시 목록 | 1시간 |
| 공시 본문, 재무제표 | 30일 |

캐시를 비우려면 파일을 지우면 됩니다.

## 알아둘 점

- 주가는 전 영업일 종가까지 제공됩니다. 실시간 시세가 아닙니다.
- 주가는 수정주가가 아닙니다. 액면분할이나 증자가 낀 기간의 수익률은 왜곡됩니다.
- `get_financials`의 분기(1~3) 손익 값은 3개월 금액이고, `quarter=4`는 사업보고서의 연간 금액입니다.
- 분기 손익의 `current_period`는 그 3개월 구간입니다. DART 원본은 누적 구간(예: 01.01 ~ 09.30)으로 표기하므로 서버가 금액에 맞게 바꿔서 돌려줍니다.
- 재무 자료는 DART 주요계정 API가 제공하는 2015년 이후 사업연도만 조회됩니다.
- 공공데이터포털은 해외 IP에서 접속이 막힐 수 있습니다. 해외 서버에서 돌리면 시세 도구가 연결 오류를 낼 수 있습니다.
- 공공데이터포털 조회가 실패해도 `resolve_ticker`는 DART만으로 종목코드와 corp_code를 돌려주고, ISIN과 시장 구분을 채우지 못했다고 `warnings`에 적습니다.
- 웹 크롤링은 하지 않습니다. 공시 본문도 DART 공식 원문 API로 받습니다.

## 개발

```bash
uv run pytest          # 키와 네트워크 없이 통과합니다
uv run ruff check .
uv run ruff format --check .
```

`tests/fixtures/`의 DART 응답은 실제 API 응답을 녹화한 것이고(개인정보는 가명·더미 값으로 바꿈), 공공데이터포털 응답은 아직 공식 문서 형식에 맞춰 만든 **샘플 값**입니다(실제 수치가 아닙니다). 자세한 내용은 [tests/fixtures/README.md](tests/fixtures/README.md)에 있습니다. 본인 키로 실제 응답을 녹화하려면:

```bash
uv run python scripts/record_fixtures.py              # 아직 녹화하지 않은 소스만
uv run python scripts/record_fixtures.py --only fsc   # 공공데이터포털만 (dart, dart_reports도 가능)
```

API별로 최대 20건을 한 번만 받아 파일로 저장합니다. 이미 녹화한 소스는 `--force` 없이는 API를 다시 호출하지 않습니다. 한 소스가 연결에 실패해도 다른 소스의 녹화는 남습니다. 테스트는 저장된 파일만 읽으므로 몇 번을 돌려도 호출 한도를 쓰지 않습니다. 녹화하면 값이 바뀌므로 `tests/test_tools.py`의 기대값도 함께 고쳐야 합니다.

레포 구조:

```
src/market_lens/
├── server.py        # MCP 서버 진입점, 도구 5개
├── sources/dart.py  # DART 공시, 재무, 고유번호
├── sources/fsc.py   # 금융위원회 주식시세, 상장종목
├── analytics.py     # 수익률·증감률 계산
├── cache.py         # SQLite TTL 캐시
├── models.py        # 응답 스키마
└── config.py        # .env 로딩
```

## 라이선스

[MIT](LICENSE)
