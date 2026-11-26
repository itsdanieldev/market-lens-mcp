# market-lens-mcp

[![PyPI](https://img.shields.io/pypi/v/market-lens-mcp)](https://pypi.org/project/market-lens-mcp/)
[![CI](https://github.com/itsdanieldev/market-lens-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/itsdanieldev/market-lens-mcp/actions/workflows/ci.yml)

[한국어](https://github.com/itsdanieldev/market-lens-mcp/blob/main/README.md) | English

An MCP server for researching Korean stocks. Connect it to an MCP client such as Claude Desktop and the model can pull disclosures, financial statements, and stock prices of listed companies from official APIs, and answer with the source and the as-of date attached.

This is not an investment recommendation tool. Please read [DISCLAIMER.md](https://github.com/itsdanieldev/market-lens-mcp/blob/main/DISCLAIMER.md) first (in Korean).

## Before you start

- **The server speaks Korean.** Tool descriptions, prompts, warnings, error messages, and the citation text are written in Korean. Company names in the data are Korean too. You can ask in English and the model will translate, but looking up a company works best with its Korean name or its 6-digit stock code (for example `005930` for Samsung Electronics).
- **You need your own API keys** from two Korean government services. Both are free, but their sign-up pages are in Korean and may ask for identity verification that is aimed at residents of Korea.
- **The price API may be unreachable from outside Korea.** The public data portal can block overseas IP addresses.

## Tools

| Tool | Input | Output | Data source |
| --- | --- | --- | --- |
| `resolve_ticker` | Company name or stock code | Short code, ISIN, DART corp_code, market | KRX listed items (FSC) + DART corp codes |
| `list_disclosures` | Company, period, disclosure type | Disclosure list (title, filing date, receipt number) | DART |
| `get_disclosure_text` | Receipt number | Disclosure body text (length-limited, resumable) | DART |
| `get_financials` | Company, year, quarter | Revenue, operating income, net income, assets, liabilities, equity | DART |
| `get_stock_prices` | Company, period | Daily OHLCV and a period summary | FSC stock price information |

DART is the electronic disclosure system of the Financial Supervisory Service. FSC is the Financial Services Commission, whose data is served through the public data portal (data.go.kr).

Every response has the same shape.

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

- `source`, `as_of`: where the data came from and the date it refers to.
- `citation`: the two combined into one sentence ("출처" means source, "기준일" means as-of date). Tool descriptions tell the model to copy it at the end of its answer. When the reference point is a time rather than a date, as with disclosure lists, it reads `기준 시각: 2026-11-26 15:20 KST` while `as_of` stays in ISO format.
- `computed`: values the server calculates in code, such as growth rates, margins, debt ratio, and period return. They exist so the model does not do arithmetic in its head.

## Installation

You only need [uv](https://docs.astral.sh/uv/). `uvx` downloads the package from [PyPI](https://pypi.org/project/market-lens-mcp/) and runs it, so there is nothing to install separately. Python 3.11 or later is required, and `uv` fetches it if it is missing.

```bash
uvx market-lens-mcp
```

You rarely run this command yourself. Put it in your MCP client's configuration, as in "Claude Desktop setup" below, and the client runs it. Get your own keys and pass them through `env` in the client configuration. The package and the repository contain no keys.

To use the latest code that has not been released yet, run it straight from GitHub.

```bash
uvx --from git+https://github.com/itsdanieldev/market-lens-mcp market-lens-mcp
```

To change the code or keep your keys in a `.env` file, clone the repository (see "Development").

## Getting the keys

Both are free.

**DART_API_KEY**

1. Sign up at [opendart.fss.or.kr](https://opendart.fss.or.kr).
2. Go to 인증키 신청/관리 (API key application) → 인증키 신청 (apply).
3. The 40-character key you receive is `DART_API_KEY`.

**DATA_GO_KR_KEY**

1. Sign up at [data.go.kr](https://www.data.go.kr).
2. Click 활용신청 (request access) on each of the two APIs below. Approval is automatic.
   - [금융위원회_주식시세정보](https://www.data.go.kr/data/15094808/openapi.do) (FSC stock price information)
   - [금융위원회_KRX상장종목정보](https://www.data.go.kr/data/15094775/openapi.do) (FSC KRX listed items)
3. The general authentication key on your account page is `DATA_GO_KR_KEY`. Both the Encoding and the Decoding form work.

Right after approval you may get `SERVICE_KEY_IS_NOT_REGISTERED_ERROR` until the key becomes active. Try again a little later.

The server calls the portal's V2 endpoints (`GetStockSecuritiesInfoService_V2/getStockPriceInfo_V2`, `GetKrxListedInfoService_V2/getItemInfo_V2`). The pre-V2 endpoints return the same error even with a valid key.

Some tools work with only one key. The disclosure and financial tools need only the DART key, and `get_stock_prices` needs only the portal key. `resolve_ticker` works with either one and leaves blank the fields that come from the missing source.

## Providing the keys

The server reads the environment variables `DART_API_KEY` and `DATA_GO_KR_KEY`. Choose one of two ways to set them. If both are present, environment variables take precedence over `.env`.

**In the MCP client's `env`**: the client passes them when it starts the server, as in the "Claude Desktop setup" example below.

**In a `.env` file**: for when you run from a cloned repository. Create the file with `cp .env.example .env` in the repository root and fill in the values. `.env` is not tracked by git.

```bash
DART_API_KEY=your_40_character_key
DATA_GO_KR_KEY=your_general_authentication_key
# Optional: cache directory (default ~/.cache/market-lens)
# MARKET_LENS_CACHE_DIR=
```

Use only your own keys and do not share them. Call quotas are per key, and committing a configuration file or `.env` to a public repository exposes the key.

## Claude Desktop setup

Open `claude_desktop_config.json` through Settings → Desktop app → Extensions → Local MCP servers → "Edit config", add the block below, then quit the app completely and start it again. Menu names can differ between app versions.

```json
{
  "mcpServers": {
    "market-lens": {
      "command": "uvx",
      "args": ["market-lens-mcp"],
      "env": {
        "DART_API_KEY": "your_40_character_key",
        "DATA_GO_KR_KEY": "your_general_authentication_key"
      }
    }
  }
}
```

After the restart, the server is connected if `market-lens` shows as running on the same screen. If the app cannot find `uvx`, put the full path from `which uvx` in `command`.

When a new version is released, `uvx` may keep using the older one it already downloaded. To switch to the latest, run `uv cache clean market-lens-mcp` and restart the app.

In Claude Code, register it like this.

```bash
claude mcp add market-lens -e DART_API_KEY=your_40_character_key -e DATA_GO_KR_KEY=your_general_authentication_key \
  -- uvx market-lens-mcp
```

If you run from a cloned repository, change `command` and `args` as below, using the absolute path of your clone. If your keys are in a `.env` file, you can leave out the `env` block.

```json
"command": "uv",
"args": ["--directory", "/absolute/path/to/market-lens-mcp", "run", "market-lens-mcp"]
```

## Usage

Once the server is connected, ask in the conversation as you normally would and the model picks the tools it needs. There is no separate command for running a tool. To make it follow a fixed sequence, choose one of the prompts the server provides.

### Example questions per tool

| Tool | Ask like this |
| --- | --- |
| `resolve_ticker` | Use market-lens to look up the stock code and ISIN for 삼성전자 |
| `get_financials` | Use market-lens to get SK하이닉스 results for Q3 2025 |
| `list_disclosures` | Use market-lens to list 카카오's material event disclosures from the past month |
| `get_disclosure_text` | Read the first disclosure in that list and summarize the key points |
| `get_stock_prices` | Use market-lens to show 현대차's price trend and period return over the last 90 days |

You can have it use several tools at once, for example: `Use market-lens to summarize 삼성전자's latest results and disclosures`

You can put these conditions in a question.

- Company: name or 6-digit stock code
- Financials: fiscal year and quarter (Q1 to Q3, or the full year)
- Disclosures: period and disclosure type (periodic reports, material events, ownership filings, and so on)
- Prices: period (the last 90 days if omitted)

### Starting from a prompt

The server provides three prompts. Pick one from your client's prompt menu and enter a company, and it builds a request that spells out which tools to use in which order, along with the answer rules. Because you choose it yourself, the model has less room to skip the tools. The prompt titles and text are in Korean.

| Prompt | Input | What it does |
| --- | --- | --- |
| 종목 브리핑 (`stock_briefing`) | Company | Confirm the company → latest quarterly results → disclosures from the last 30 days → body of key disclosures → prices for the last 90 days |
| 실적 정리 (`earnings_review`) | Company, period (optional) | Fetch the results and check the underlying report for the reasons behind the changes |
| 공시 요약 (`disclosure_digest`) | Company, days (optional, default 30) | Group disclosures by kind and read the body of the important ones |

Where the prompt menu is and what it is called depends on the client. In clients that do not support prompts, use the methods below.

### Checking that a tool was called

- A tool call indicator such as `market-lens: Get financials` appears above or within the answer. Expand it to see the arguments sent and the raw response (JSON).
- The answer ends with `출처: … · 기준일: …`, the same text as `citation` in the raw response.
- If neither is there, the model answered from memory or web search without using the tools. The numbers in that answer did not come from this server.

### Making sure the tools are used

Tool descriptions say "for results, disclosures, and prices of Korean listed companies, use this tool first", but whether to call a tool is the model's decision. The same question sometimes triggers a tool and sometimes does not. To have the tools used every time, do one of the following.

- Mention the tool in your question. Adding `Use market-lens to` as in the examples above is enough.
- Add a line to your client's project instructions or personal preferences, for example: `For stock codes, disclosures, financial results, and prices of Korean stocks, query the market-lens tools and write the citation from the tool response at the end of the answer.`

## Cache

Responses are stored in SQLite (`~/.cache/market-lens/cache.sqlite3`) to save API quota. Change the location with `MARKET_LENS_CACHE_DIR`.

| Data | Lifetime |
| --- | --- |
| Stock prices | The current day (until midnight KST) |
| Listed items, DART corp codes | 1 day |
| Disclosure lists | 1 hour |
| Disclosure bodies, financial statements | 30 days (an empty response for a report not yet filed is not stored) |

To clear the cache, delete the file.

## Things to know

- Prices are available up to the previous business day's close. They are not real-time. The portal publishes data after 1 p.m. on the day following a business day (Friday's data on the next Monday).
- The KRX listed items API does not include preferred shares. So `resolve_ticker` cannot find a preferred share, and neither can `get_stock_prices` when given the name of one.
- When you give `get_stock_prices` a company name, it must match the KRX item name exactly (for example NAVER, not 네이버). If it does not, the error message suggests similar items. A 6-digit stock code is looked up as is.
- Prices are not adjusted. Returns over a period that includes a stock split or a capital increase are distorted.
- In `get_financials`, the income figures for quarters 1 to 3 are three-month amounts, and `quarter=4` is the full-year amount from the annual report.
- `current_period` for a quarterly income figure is that three-month span. DART labels it with the cumulative span (for example 01.01 ~ 09.30), so the server rewrites it to match the amount.
- Financial data covers fiscal years from 2015 onward, which is what the DART key accounts API provides.
- The public data portal may block access from overseas IP addresses. On a server outside Korea, the price tool can fail with a connection error.
- If the portal lookup fails, `resolve_ticker` still returns the stock code and corp_code from DART alone and notes in `warnings` that it could not fill in the ISIN and market.
- The source and the as-of date are in every tool response, but the model writes the final answer and may leave them out. In that case, expand the tool call in your client and check `citation` in the raw response.
- The server does no web scraping. Disclosure bodies come from DART's official document API.

## Development

You need Python 3.11 or later and [uv](https://docs.astral.sh/uv/). The server uses version 2.x of the MCP Python SDK (`MCPServer`).

```bash
git clone https://github.com/itsdanieldev/market-lens-mcp.git
cd market-lens-mcp
uv sync
uv run pytest          # passes without keys or network access
uv run ruff check .
uv run ruff format --check .
```

The DART responses in `tests/fixtures/` are recordings of real API responses, with personal information replaced by pseudonyms and dummy values. The portal responses are samples with made-up values in the same structure as the real responses, because the portal's terms of use prohibit redistributing the data. See [tests/fixtures/README.md](https://github.com/itsdanieldev/market-lens-mcp/blob/main/tests/fixtures/README.md) for details (in Korean). To fetch real responses with your own keys:

```bash
uv run python scripts/record_fixtures.py              # only sources not recorded yet
uv run python scripts/record_fixtures.py --only fsc   # the portal only (dart and dart_reports also work)
```

The script fetches at most 20 rows per API, once, and saves them to files. A source that is already recorded is not called again without `--force`. If one source fails to connect, the recordings of the others are kept. Tests read only the saved files, so running them any number of times uses no quota. Recording changes the values, so update the expected values in `tests/test_tools.py` as well. Do not commit the results of recording the portal (`fsc`).

To release, bump the version in both `pyproject.toml` and `src/market_lens/__init__.py`, then push a tag such as `v0.1.0`. `.github/workflows/release.yml` tests, builds, and publishes to PyPI. The publish step waits for approval in the `pypi` environment on GitHub. It uses PyPI Trusted Publishing so that no token is stored in the repository, which requires registering this repository and workflow as a trusted publisher on PyPI first.

Repository layout:

```
src/market_lens/
├── server.py        # MCP server entry point: names, arguments, and descriptions of 5 tools and 3 prompts
├── prompts.py       # prompt text
├── app.py           # wires settings, cache, HTTP, and source clients together
├── services/        # per-tool logic: tickers, disclosures, financials, prices
├── sources/dart.py  # DART disclosures, financials, corp codes (parses raw responses)
├── sources/fsc.py   # FSC stock prices, listed items (parses raw responses)
├── sources/_base.py # retries, caching, error handling that does not leak keys
├── analytics.py     # return and growth-rate calculations
├── cache.py         # SQLite TTL cache
├── models.py        # response schema
├── errors.py        # errors passed on to the model
├── util.py          # date and number parsing
└── config.py        # environment variables and .env loading
scripts/record_fixtures.py  # records real responses
tests/                      # tests that run on fixtures
```

## License

[MIT](https://github.com/itsdanieldev/market-lens-mcp/blob/main/LICENSE)
