"""실제 API 응답을 받아 tests/fixtures/의 샘플을 교체한다.

.env에 DART_API_KEY, DATA_GO_KR_KEY가 있어야 한다. 키는 요청 파라미터로만 쓰이고
응답 본문에는 들어 있지 않으므로 저장되는 파일에 남지 않는다.

    uv run python scripts/record_fixtures.py

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
    settings = load_settings()
    if not (settings.dart_api_key and settings.data_go_kr_key):
        print("DART_API_KEY와 DATA_GO_KR_KEY를 .env에 넣어 주세요.", file=sys.stderr)
        return 1
    today = now_kst().date()
    dart_key = {"crtfc_key": settings.dart_api_key}
    fsc_common = {"serviceKey": settings.data_go_kr_key, "resultType": "json", "numOfRows": 100}

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
                    "page_count": 100,
                },
            ),
        )
        # 가장 짧은 원문 하나를 고른다.
        for row in listing.get("list") or []:
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
    print("끝. 기대값을 고친 뒤 uv run pytest로 확인하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
