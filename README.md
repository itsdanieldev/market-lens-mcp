# market-lens-mcp

[![PyPI](https://img.shields.io/pypi/v/market-lens-mcp)](https://pypi.org/project/market-lens-mcp/)
[![CI](https://github.com/itsdanieldev/market-lens-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/itsdanieldev/market-lens-mcp/actions/workflows/ci.yml)

한국 주식 리서치용 MCP 서버입니다. Claude Desktop 같은 MCP 클라이언트에 붙이면 상장사의 공시, 재무제표, 주가를 공식 API에서 가져와 출처와 기준일이 붙은 답을 만들 수 있습니다.

투자 권유 도구가 아닙니다. [DISCLAIMER.md](DISCLAIMER.md)를 먼저 읽어 주세요.

## 도구

| 도구 | 입력 | 출력 | 데이터 소스 |
| --- | --- | --- | --- |
| `resolve_ticker` | 종목명 또는 종목코드 | 단축코드, ISIN, DART corp_code, 시장 | KRX상장종목정보 + DART 고유번호 |
| `list_disclosures` | 종목, 기간, 공시유형 | 공시 목록(제목, 접수일, 접수번호) | DART |
| `get_disclosure_text` | 접수번호 | 공시 본문 텍스트(길이 제한, 이어 읽기) | DART |
| `get_financials` | 종목, 연도, 분기 | 매출, 영업이익, 순이익, 자산, 부채, 자본 | DART |
| `get_stock_prices` | 종목, 기간 | 일별 OHLCV, 기간 수익률 요약 | 금융위원회 주식시세정보 |

모든 응답은 같은 형식입니다.

```json
{
  "source": "DART OpenAPI (금융감독원 전자공시시스템)",
  "as_of": "2024-09-30",
  "citation": "출처: DART OpenAPI (금융감독원 전자공시시스템) · 기준일: 2024-09-30",
  "fetched_at": "2024-11-15T09:12:03+09:00",
  "cached": false,
  "data": { },
  "computed": { "revenue_change_pct": 12.5 },
  "warnings": [],
  "disclaimer": "…"
}
```

- `source`, `as_of`: 출처와 데이터 기준일.
- `citation`: 위 둘을 합친 인용 문구. 모델이 답변 끝에 그대로 옮겨 적도록 도구 설명에서 지시합니다. 공시 목록처럼 기준이 시각이면 `기준 시각: 2026-11-26 15:20 KST`처럼 풀어 씁니다(`as_of`는 ISO 형식 그대로).
- `computed`: 증감률, 이익률, 부채비율, 기간 수익률처럼 서버가 코드로 계산한 값. 모델이 암산하지 않게 하기 위한 필드입니다.

## 설치

[uv](https://docs.astral.sh/uv/)만 있으면 됩니다. `uvx`가 [PyPI](https://pypi.org/project/market-lens-mcp/)에서 받아 바로 실행하므로 따로 설치할 것이 없습니다. Python 3.11 이상이 필요하고, 없으면 `uv`가 받아 줍니다.

```bash
uvx market-lens-mcp
```

이 명령을 직접 실행할 일은 거의 없고, 아래 "Claude Desktop 설정"처럼 MCP 클라이언트 설정에 적어 두면 클라이언트가 실행합니다. 키는 직접 발급받아 클라이언트 설정의 `env`로 넘깁니다. 패키지와 저장소에는 키가 들어 있지 않습니다.

아직 배포되지 않은 최신 코드를 쓰려면 GitHub에서 바로 받습니다.

```bash
uvx --from git+https://github.com/itsdanieldev/market-lens-mcp market-lens-mcp
```

코드를 고치거나 `.env` 파일로 키를 관리하려면 저장소를 받습니다("개발" 참고).

## 키 발급

둘 다 무료입니다.

**DART_API_KEY**

1. [opendart.fss.or.kr](https://opendart.fss.or.kr)에서 회원가입
2. 인증키 신청/관리 → 인증키 신청
3. 발급된 40자리 키가 `DART_API_KEY`

**DATA_GO_KR_KEY**

1. [data.go.kr](https://www.data.go.kr)에서 회원가입
2. 아래 두 API에서 각각 "활용신청" (자동승인)
   - [금융위원회_주식시세정보](https://www.data.go.kr/data/15094808/openapi.do)
   - [금융위원회_KRX상장종목정보](https://www.data.go.kr/data/15094775/openapi.do)
3. 마이페이지의 일반 인증키가 `DATA_GO_KR_KEY` (Encoding, Decoding 키 모두 됩니다)

승인 직후에는 키가 반영될 때까지 `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`가 날 수 있습니다. 잠시 뒤 다시 시도하세요.

두 API는 포털의 V2 주소(`GetStockSecuritiesInfoService_V2/getStockPriceInfo_V2`, `GetKrxListedInfoService_V2/getItemInfo_V2`)로 호출합니다. V2 이전 주소는 키가 맞아도 같은 오류를 돌려줍니다.

키가 하나만 있어도 일부 도구는 동작합니다. 공시·재무 도구는 DART 키만, `get_stock_prices`는 공공데이터포털 키만 있으면 됩니다. `resolve_ticker`는 둘 중 하나만 있어도 되고, 없는 쪽에서 오는 항목은 비워 둡니다.

## 키 넣기

서버는 환경변수 `DART_API_KEY`, `DATA_GO_KR_KEY`를 읽습니다. 넣는 방법은 둘 중 하나를 고릅니다. 둘 다 있으면 환경변수가 `.env`보다 먼저입니다.

**MCP 클라이언트 설정의 `env`에 넣기**: 아래 "Claude Desktop 설정"의 예시처럼 클라이언트가 서버를 띄울 때 넘겨줍니다.

**`.env` 파일에 넣기**: 저장소를 받아서 쓸 때의 방법입니다. 저장소 루트에서 `cp .env.example .env`로 파일을 만들고 값을 채웁니다. `.env`는 git에 올라가지 않습니다.

```bash
DART_API_KEY=발급받은_40자리_키
DATA_GO_KR_KEY=발급받은_일반_인증키
# 선택: 캐시 디렉터리 (기본값 ~/.cache/market-lens)
# MARKET_LENS_CACHE_DIR=
```

키는 본인 것만 쓰고 다른 사람과 나누지 마세요. 호출 한도가 키마다 정해져 있고, 설정 파일이나 `.env`를 공개 저장소에 올리면 키가 노출됩니다.

## Claude Desktop 설정

설정 → 데스크톱 앱 → 확장 프로그램 → 로컬 MCP 서버의 "구성 편집"으로 `claude_desktop_config.json`을 열고 아래를 추가한 뒤 앱을 완전히 종료했다가 다시 시작합니다(앱 버전에 따라 메뉴 이름이 다를 수 있습니다).

```json
{
  "mcpServers": {
    "market-lens": {
      "command": "uvx",
      "args": ["market-lens-mcp"],
      "env": {
        "DART_API_KEY": "발급받은_40자리_키",
        "DATA_GO_KR_KEY": "발급받은_일반_인증키"
      }
    }
  }
}
```

다시 시작한 뒤 같은 화면에 `market-lens`가 실행 중으로 보이면 연결된 것입니다. 앱이 `uvx`를 찾지 못하면 `command`에 `which uvx`로 확인한 전체 경로를 적습니다.

새 버전이 나오면 `uvx`가 받아 둔 예전 버전을 계속 쓸 수 있습니다. 최신 버전으로 바꾸려면 `uv cache clean market-lens-mcp`를 실행하고 앱을 다시 시작합니다.

Claude Code에서는 다음처럼 등록합니다.

```bash
claude mcp add market-lens -e DART_API_KEY=발급받은_40자리_키 -e DATA_GO_KR_KEY=발급받은_일반_인증키 \
  -- uvx market-lens-mcp
```

저장소를 받아서 쓰는 경우에는 `command`와 `args`를 아래처럼 바꿉니다. 경로는 저장소를 받은 절대 경로입니다. 키를 `.env` 파일에 넣었다면 `env` 블록은 빼도 됩니다.

```json
"command": "uv",
"args": ["--directory", "/절대/경로/market-lens-mcp", "run", "market-lens-mcp"]
```

## 사용법

MCP 클라이언트에 연결한 뒤 대화에서 평소처럼 물어보면 모델이 필요한 도구를 골라 부릅니다. 도구를 직접 실행하는 명령은 따로 없습니다. 정해진 흐름대로 조회하게 하려면 서버가 제공하는 프롬프트를 고르면 됩니다.

### 도구별 질문 예시

| 도구 | 이렇게 물어보세요 |
| --- | --- |
| `resolve_ticker` | market-lens로 삼성전자 종목코드와 ISIN 조회해줘 |
| `get_financials` | market-lens로 SK하이닉스 2025년 3분기 실적 알려줘 |
| `list_disclosures` | market-lens로 카카오 최근 한 달 주요사항보고 공시 목록 보여줘 |
| `get_disclosure_text` | 방금 목록의 첫 번째 공시 본문 읽고 핵심만 정리해줘 |
| `get_stock_prices` | market-lens로 현대차 최근 90일 주가 흐름과 기간 수익률 알려줘 |

여러 도구를 한 번에 쓰게 할 수도 있습니다. 예: `market-lens로 삼성전자 최근 실적과 공시 요약해줘`

질문에 넣을 수 있는 조건은 다음과 같습니다.

- 종목: 종목명 또는 6자리 종목코드
- 실적: 사업연도와 분기(1~3분기, 또는 연간)
- 공시: 기간과 공시유형(정기공시, 주요사항보고, 지분공시 등)
- 주가: 기간(생략하면 최근 90일)

### 프롬프트로 시작하기

서버가 프롬프트 3개를 제공합니다. 클라이언트의 프롬프트 메뉴에서 고르고 종목만 입력하면, 어떤 도구를 어떤 순서로 쓸지와 답변 규칙이 담긴 요청이 만들어집니다. 사용자가 직접 고르는 것이라 모델이 도구를 건너뛸 여지가 줄어듭니다.

| 프롬프트 | 입력 | 하는 일 |
| --- | --- | --- |
| 종목 브리핑 (`stock_briefing`) | 종목 | 종목 확인 → 최근 분기 실적 → 최근 30일 공시 → 주요 공시 본문 → 최근 90일 주가 |
| 실적 정리 (`earnings_review`) | 종목, 기간(선택) | 실적을 조회하고 근거 보고서에서 변동 배경을 확인 |
| 공시 요약 (`disclosure_digest`) | 종목, 일수(선택, 기본 30) | 공시를 종류별로 묶고 중요한 공시는 본문을 읽어 요약 |

프롬프트 메뉴의 위치와 이름은 클라이언트마다 다릅니다. 프롬프트를 지원하지 않는 클라이언트에서는 아래 방법을 쓰세요.

### 도구가 호출됐는지 확인하기

- 답변 위나 중간에 `market-lens: Get financials` 같은 도구 호출 표시가 생깁니다. 펼치면 보낸 인자와 응답 원본(JSON)이 보입니다.
- 답변 끝에 `출처: … · 기준일: …`이 붙습니다. 응답 원본의 `citation`과 같은 문구입니다.
- 둘 다 없으면 도구를 쓰지 않고 모델이 기억이나 웹 검색으로 답한 것입니다. 그 답의 숫자는 이 서버가 준 값이 아닙니다.

### 도구를 확실히 쓰게 하려면

도구 설명에 "한국 상장사의 실적·공시·주가는 이 도구를 먼저 쓴다"고 적어 두었지만, 도구를 부를지는 모델이 정합니다. 같은 질문에도 도구를 쓸 때가 있고 쓰지 않을 때가 있습니다. 항상 쓰게 하려면 둘 중 하나를 하세요.

- 질문에 도구를 언급합니다. 위 예시처럼 `market-lens로`를 붙이면 됩니다.
- 클라이언트의 프로젝트 지침이나 개인 설정에 한 줄을 넣습니다. 예: `한국 주식의 종목코드, 공시, 실적, 주가는 market-lens 도구로 조회하고, 답변 끝에 도구 응답의 citation을 적는다.`

## 캐시

호출 한도를 아끼려고 응답을 SQLite(`~/.cache/market-lens/cache.sqlite3`)에 저장합니다. 위치는 `MARKET_LENS_CACHE_DIR`로 바꿉니다.

| 데이터 | 유효 기간 |
| --- | --- |
| 주가 | 당일(KST 자정까지) |
| 상장종목 목록, DART 고유번호 | 1일 |
| 공시 목록 | 1시간 |
| 공시 본문, 재무제표 | 30일 (아직 제출되지 않아 빈 응답이면 저장하지 않음) |

캐시를 비우려면 파일을 지우면 됩니다.

## 알아둘 점

- 주가는 전 영업일 종가까지 제공됩니다. 실시간 시세가 아닙니다. 포털은 영업일 다음 날 오후 1시 이후에 자료를 올립니다(금요일 자료는 다음 월요일).
- KRX상장종목정보는 우선주를 제공하지 않습니다. 그래서 `resolve_ticker`는 우선주를 찾지 못하고, `get_stock_prices`에 우선주 이름을 넣어도 찾지 못합니다.
- `get_stock_prices`에 종목명을 넣으면 KRX 종목명과 정확히 같아야 합니다(예: 네이버가 아니라 NAVER). 다르면 비슷한 종목을 오류 메시지로 알려 줍니다. 6자리 종목코드는 그대로 조회합니다.
- 주가는 수정주가가 아닙니다. 액면분할이나 증자가 낀 기간의 수익률은 왜곡됩니다.
- `get_financials`의 분기(1~3) 손익 값은 3개월 금액이고, `quarter=4`는 사업보고서의 연간 금액입니다.
- 분기 손익의 `current_period`는 그 3개월 구간입니다. DART 원본은 누적 구간(예: 01.01 ~ 09.30)으로 표기하므로 서버가 금액에 맞게 바꿔서 돌려줍니다.
- 재무 자료는 DART 주요계정 API가 제공하는 2015년 이후 사업연도만 조회됩니다.
- 공공데이터포털은 해외 IP에서 접속이 막힐 수 있습니다. 해외 서버에서 돌리면 시세 도구가 연결 오류를 낼 수 있습니다.
- 공공데이터포털 조회가 실패해도 `resolve_ticker`는 DART만으로 종목코드와 corp_code를 돌려주고, ISIN과 시장 구분을 채우지 못했다고 `warnings`에 적습니다.
- 출처와 기준일은 모든 도구 응답에 들어 있지만, 최종 답변에 적는 것은 모델이라 빠질 수 있습니다. 그럴 때는 클라이언트에서 도구 호출을 펼쳐 응답 원본의 `citation`을 확인하세요.
- 웹 크롤링은 하지 않습니다. 공시 본문도 DART 공식 원문 API로 받습니다.

## 개발

Python 3.11 이상과 [uv](https://docs.astral.sh/uv/)가 필요합니다. MCP Python SDK는 2.x(`MCPServer`)를 씁니다.

```bash
git clone https://github.com/itsdanieldev/market-lens-mcp.git
cd market-lens-mcp
uv sync
uv run pytest          # 키와 네트워크 없이 통과합니다
uv run ruff check .
uv run ruff format --check .
```

`tests/fixtures/`의 DART 응답은 실제 API 응답을 녹화한 것입니다(개인정보는 가명·더미 값으로 바꿈). 공공데이터포털 응답은 실제 응답과 같은 구조에 지어낸 값을 넣은 샘플입니다. 포털의 이용허락범위가 데이터 재배포를 금지하기 때문입니다. 자세한 내용은 [tests/fixtures/README.md](tests/fixtures/README.md)에 있습니다. 본인 키로 실제 응답을 받아 보려면:

```bash
uv run python scripts/record_fixtures.py              # 아직 녹화하지 않은 소스만
uv run python scripts/record_fixtures.py --only fsc   # 공공데이터포털만 (dart, dart_reports도 가능)
```

API별로 최대 20건을 한 번만 받아 파일로 저장합니다. 이미 녹화한 소스는 `--force` 없이는 API를 다시 호출하지 않습니다. 한 소스가 연결에 실패해도 다른 소스의 녹화는 남습니다. 테스트는 저장된 파일만 읽으므로 몇 번을 돌려도 호출 한도를 쓰지 않습니다. 녹화하면 값이 바뀌므로 `tests/test_tools.py`의 기대값도 함께 고쳐야 합니다. 공공데이터포털(`fsc`) 녹화 결과는 커밋하지 마세요.

릴리스는 `pyproject.toml`과 `src/market_lens/__init__.py`의 버전을 함께 올린 뒤 `v0.1.0` 같은 태그를 푸시하면 `.github/workflows/release.yml`이 테스트, 빌드, PyPI 배포를 합니다. 배포 단계는 GitHub의 `pypi` 환경에서 승인해야 진행됩니다. 토큰을 저장소에 두지 않도록 PyPI의 Trusted Publishing을 쓰며, PyPI에서 이 저장소와 워크플로를 신뢰할 게시자로 먼저 등록해야 합니다.

레포 구조:

```
src/market_lens/
├── server.py        # MCP 서버 진입점: 도구 5개와 프롬프트 3개의 이름, 인자, 설명
├── prompts.py       # 프롬프트 문구
├── app.py           # 설정·캐시·HTTP·소스 클라이언트 조립
├── services/        # 도구별 처리: tickers, disclosures, financials, prices
├── sources/dart.py  # DART 공시, 재무, 고유번호 (원본 응답 해석)
├── sources/fsc.py   # 금융위원회 주식시세, 상장종목 (원본 응답 해석)
├── sources/_base.py # 재시도, 캐시, 키가 새지 않는 오류 처리
├── analytics.py     # 수익률·증감률 계산
├── cache.py         # SQLite TTL 캐시
├── models.py        # 응답 스키마
├── errors.py        # 모델에게 전달되는 오류
├── util.py          # 날짜·숫자 파싱
└── config.py        # 환경변수, .env 로딩
scripts/record_fixtures.py  # 실제 응답 녹화
tests/                      # 픽스처로 도는 테스트
```

## 라이선스

[MIT](LICENSE)
