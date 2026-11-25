"""실제 API 응답을 받아 tests/fixtures/의 샘플을 교체한다.

.env에 DART_API_KEY, DATA_GO_KR_KEY가 있어야 한다. 키는 요청 파라미터로만 쓰이고
응답 본문에는 들어 있지 않으므로 저장되는 파일에 남지 않는다.

    uv run python scripts/record_fixtures.py          # 최초 1회만 호출
    uv run python scripts/record_fixtures.py --force  # 다시 받아 덮어쓰기

API별로 최대 20건만 한 번 받아 파일로 저장하고, 이후 테스트는 그 파일만 읽는다.
이미 녹화한 적이 있으면(RECORDED.json 존재) API를 호출하지 않고 끝낸다.

주의: 값이 실제 수치로 바뀌므로 tests/test_tools.py의 기대값도 함께 고쳐야 한다.
"""

from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from datetime import timedelta
from pathlib import Path

import httpx

from kr_invest.config import load_settings
from kr_invest.sources import dart, fsc
from kr_invest.util import now_kst, ymd

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
CORP_CODE = "00126380"  # 삼성전자
STOCK_CODE = "005930"
SAMPLE_STOCK_CODES = ("005930", "006400", "000660")
MAX_DOCUMENT_BYTES = 200_000
MAX_ROWS = 20  # API별로 받아 오는 최대 건수
MAX_DOCUMENT_TRIES = 3
MANIFEST = FIXTURES / "RECORDED.json"


def save_json(name: str, response: httpx.Response) -> dict:
    payload = response.json()
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    (FIXTURES / name).write_text(text + "\n", encoding="utf-8")
    print(f"저장: {name}")
    return payload


def unzip_first(content: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return archive.read(archive.namelist()[0])


def main() -> int:
    if MANIFEST.exists() and "--force" not in sys.argv[1:]:
        print(f"이미 녹화돼 있습니다({MANIFEST.name}). 다시 받으려면 --force를 붙이세요.")
        return 0
    settings = load_settings()
    if not (settings.dart_api_key and settings.data_go_kr_key):
        print("DART_API_KEY와 DATA_GO_KR_KEY를 .env에 넣어 주세요.", file=sys.stderr)
        return 1
    today = now_kst().date()
    dart_key = {"crtfc_key": settings.dart_api_key}
    fsc_common = {
        "serviceKey": settings.data_go_kr_key,
        "resultType": "json",
        "numOfRows": MAX_ROWS,
    }

    with httpx.Client(timeout=30.0) as http:
        # 고유번호 전체는 수십 MB라 샘플 종목만 남긴다.
        xml = unzip_first(http.get(f"{dart.BASE_URL}/corpCode.xml", params=dart_key).content)
        entries = re.findall(r"<list>.*?</list>", xml.decode("utf-8"), flags=re.S)
        kept = [e for e in entries if any(f">{c}<" in e for c in SAMPLE_STOCK_CODES)]
        body = "\n  ".join(kept)
        (FIXTURES / "dart_corpcode.xml").write_text(
            f'<?xml version="1.0" encoding="UTF-8"?>\n<result>\n  {body}\n</result>\n',
            encoding="utf-8",
        )
        print("저장: dart_corpcode.xml")

        listing = save_json(
            "dart_list.json",
            http.get(
                f"{dart.BASE_URL}/list.json",
                params={
                    **dart_key,
                    "corp_code": CORP_CODE,
                    "bgn_de": ymd(today - timedelta(days=30)),
                    "end_de": ymd(today),
                    "page_count": MAX_ROWS,
                },
            ),
        )
        # 크기가 작은 원문 하나만 저장한다(시도는 최대 3건).
        for row in (listing.get("list") or [])[:MAX_DOCUMENT_TRIES]:
            response = http.get(
                f"{dart.BASE_URL}/document.xml", params={**dart_key, "rcept_no": row["rcept_no"]}
            )
            if not zipfile.is_zipfile(io.BytesIO(response.content)):
                continue
            document = unzip_first(response.content)
            if len(document) <= MAX_DOCUMENT_BYTES:
                (FIXTURES / "dart_document.xml").write_bytes(document)
                print(f"저장: dart_document.xml (접수번호 {row['rcept_no']})")
                break

        save_json(
            "dart_financials.json",
            http.get(
                f"{dart.BASE_URL}/fnlttSinglAcnt.json",
                params={
                    **dart_key,
                    "corp_code": CORP_CODE,
                    "bsns_year": str(today.year - 1),
                    "reprt_code": dart.REPORT_CODES[3],
                },
            ),
        )
        save_json(
            "fsc_items.json",
            http.get(
                fsc.ITEM_URL,
                params={
                    **fsc_common,
                    "likeItmsNm": "삼성전자",
                    "beginBasDt": ymd(today - timedelta(days=fsc.ITEM_LOOKBACK_DAYS)),
                },
            ),
        )
        save_json(
            "fsc_prices.json",
            http.get(
                fsc.PRICE_URL,
                params={
                    **fsc_common,
                    "likeSrtnCd": STOCK_CODE,
                    "beginBasDt": ymd(today - timedelta(days=14)),
                },
            ),
        )
    MANIFEST.write_text(
        json.dumps({"recorded_on": today.isoformat(), "max_rows": MAX_ROWS}, indent=1) + "\n",
        encoding="utf-8",
    )
    print("끝. 기대값을 고친 뒤 uv run pytest로 확인하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
