"""실제 API 응답을 받아 tests/fixtures/에 저장한다.

.env(또는 환경변수)에 DART_API_KEY, DATA_GO_KR_KEY가 있어야 한다. 키는 요청 파라미터로만
쓰이고 응답 본문에는 들어 있지 않다. 저장 직전에 본문에 키가 섞여 있지 않은지 한 번 더 확인한다.

공시에는 개인 제출인(임원·주주)의 이름, 생년월일, 주소가 실려 있다. 저장소에 개인정보를
남기지 않도록 공시 목록의 개인 제출인 이름은 가명으로 바꾸고, 원문은 회사가 직접 낸 공시만 고른다.
그래도 커밋 전에 저장된 파일에 개인정보가 없는지 직접 확인해야 한다.

    uv run python scripts/record_fixtures.py              # 아직 녹화하지 않은 소스만
    uv run python scripts/record_fixtures.py --only dart  # DART만 (dart_reports: 보고서 종류별 재무)
    uv run python scripts/record_fixtures.py --only fsc   # 공공데이터포털만
    uv run python scripts/record_fixtures.py --force      # 이미 녹화한 소스도 다시 받기

API별로 최대 20건만 한 번 받아 파일로 저장하고, 이후 테스트는 그 파일만 읽는다.
녹화가 끝난 소스는 RECORDED.json에 적히고, --force 없이는 다시 호출하지 않는다.
한 소스가 실패해도(예: 해외 IP에서 공공데이터포털 연결 실패) 다른 소스의 녹화는 남는다.
실패한 소스는 파일을 건드리지 않으며, 같은 실행 안에서 다시 시도하지도 않는다.

주의: 값이 실제 수치로 바뀌므로 tests/test_tools.py의 기대값도 함께 고쳐야 한다.
공공데이터포털(fsc)은 이용허락범위가 재배포를 금지하므로 녹화 결과를 커밋하지 않는다.
저장소의 fsc_* 파일은 실제 응답 구조에 지어낸 값을 넣은 샘플이다.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import httpx

from market_lens.config import Settings, load_settings
from market_lens.sources import dart, fsc
from market_lens.util import now_kst, ymd

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
CORP_CODE = "00126380"  # 삼성전자
STOCK_CODE = "005930"
SAMPLE_STOCK_CODES = ("005930", "006400", "000660")
MAX_DOCUMENT_BYTES = 200_000
MAX_ROWS = 20  # API별로 받아 오는 최대 건수
MAX_DOCUMENT_TRIES = 3
MANIFEST = FIXTURES / "RECORDED.json"

Files = dict[str, bytes]


class RecordError(Exception):
    """응답이 기대한 형식이 아니라 저장하지 않는다."""


def as_json(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def parse_json(name: str, response: httpx.Response) -> dict:
    try:
        return response.json()
    except ValueError:
        reason = re.search(r"<returnAuthMsg>(.*?)</returnAuthMsg>", response.text)
        detail = reason.group(1) if reason else response.text[:80].strip()
        raise RecordError(
            f"{name}: JSON이 아닌 응답(HTTP {response.status_code}) {detail!r}"
        ) from None


def dart_json(name: str, response: httpx.Response) -> dict:
    payload = parse_json(name, response)
    if payload.get("status") != dart.STATUS_OK:
        raise RecordError(f"{name}: DART 오류 {payload.get('status')} {payload.get('message')}")
    return payload


def fsc_json(name: str, response: httpx.Response) -> dict:
    payload = parse_json(name, response)
    header = (payload.get("response") or {}).get("header") if isinstance(payload, dict) else None
    if not isinstance(header, dict):
        # 문서와 다른 모양의 응답이다. 원인을 볼 수 있게 앞부분을 그대로 보여 준다.
        snippet = " ".join(response.text.split())[:300]
        raise RecordError(f"{name}: 예상과 다른 응답(HTTP {response.status_code}) {snippet}")
    if header.get("resultCode") != "00":
        raise RecordError(
            f"{name}: 공공데이터포털 오류 {header.get('resultCode')} {header.get('resultMsg')}"
        )
    return payload


def unzip_first(name: str, content: bytes) -> bytes:
    if not zipfile.is_zipfile(io.BytesIO(content)):
        status = re.search(rb"<status>(.*?)</status>", content)
        detail = status.group(1).decode() if status else "알 수 없는 응답"
        raise RecordError(f"{name}: ZIP이 아닌 응답(DART 상태 {detail})")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return archive.read(archive.namelist()[0])


def mask_filers(listing: dict) -> dict:
    """회사가 아닌 개인 제출인의 이름을 '보고자01' 같은 가명으로 바꾼다."""
    aliases: dict[str, str] = {}
    for row in listing.get("list") or []:
        filer = row.get("flr_nm", "")
        if filer and filer != row.get("corp_name"):
            row["flr_nm"] = aliases.setdefault(filer, f"보고자{len(aliases) + 1:02d}")
    return listing


def record_dart(http: httpx.Client, settings: Settings, today: date) -> Files:
    key = {"crtfc_key": settings.dart_api_key}
    files: Files = {}

    # 고유번호 전체는 수십 MB라 샘플 종목만 남긴다.
    response = http.get(f"{dart.BASE_URL}/corpCode.xml", params=key)
    xml = unzip_first("dart_corpcode.xml", response.content)
    entries = re.findall(r"<list>.*?</list>", xml.decode("utf-8"), flags=re.S)
    kept = [e for e in entries if any(f">{c}<" in e for c in SAMPLE_STOCK_CODES)]
    if not kept:
        raise RecordError("dart_corpcode.xml: 샘플 종목을 찾지 못했습니다.")
    body = "\n  ".join(kept)
    files["dart_corpcode.xml"] = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<result>\n  {body}\n</result>\n'
    ).encode()

    listing = dart_json(
        "dart_list.json",
        http.get(
            f"{dart.BASE_URL}/list.json",
            params={
                **key,
                "corp_code": CORP_CODE,
                "bgn_de": ymd(today - timedelta(days=30)),
                "end_de": ymd(today),
                "page_count": MAX_ROWS,
            },
        ),
    )
    # 개인 제출인의 공시 원문에는 생년월일과 주소가 있어 회사가 낸 공시만 후보로 삼는다.
    by_company = [r for r in listing.get("list") or [] if r.get("flr_nm") == r.get("corp_name")]
    files["dart_list.json"] = as_json(mask_filers(listing))

    # 크기가 작은 원문 하나만 저장한다(시도는 최대 3건).
    for row in by_company[:MAX_DOCUMENT_TRIES]:
        response = http.get(
            f"{dart.BASE_URL}/document.xml", params={**key, "rcept_no": row["rcept_no"]}
        )
        if not zipfile.is_zipfile(io.BytesIO(response.content)):
            continue
        document = unzip_first("dart_document.xml", response.content)
        if len(document) <= MAX_DOCUMENT_BYTES:
            files["dart_document.xml"] = document
            print(f"원문: 접수번호 {row['rcept_no']} ({row.get('report_nm', '').strip()})")
            break
    else:
        print("원문: 크기 제한 안의 문서를 찾지 못해 dart_document.xml은 그대로 둡니다.")

    files["dart_financials.json"] = as_json(
        dart_json(
            "dart_financials.json",
            http.get(
                f"{dart.BASE_URL}/fnlttSinglAcnt.json",
                params={
                    **key,
                    "corp_code": CORP_CODE,
                    "bsns_year": str(today.year - 1),
                    "reprt_code": dart.REPORT_CODES[3],
                },
            ),
        )
    )
    return files


# 3분기보고서는 record_dart가 받는다. 나머지 보고서 종류는 응답 형식이 달라 따로 녹화한다.
# 이미 제출된 것이 확실한 연도만 고른다: (파일 이름, 분기, 오늘 기준 몇 해 전)
REPORT_FIXTURES = (
    ("dart_financials_q1.json", 1, 1),
    ("dart_financials_half.json", 2, 1),
    ("dart_financials_annual.json", 4, 2),
)


def record_dart_reports(http: httpx.Client, settings: Settings, today: date) -> Files:
    files: Files = {}
    for filename, quarter, years_ago in REPORT_FIXTURES:
        response = http.get(
            f"{dart.BASE_URL}/fnlttSinglAcnt.json",
            params={
                "crtfc_key": settings.dart_api_key,
                "corp_code": CORP_CODE,
                "bsns_year": str(today.year - years_ago),
                "reprt_code": dart.REPORT_CODES[quarter],
            },
        )
        files[filename] = as_json(dart_json(filename, response))
    return files


def record_fsc(http: httpx.Client, settings: Settings, today: date) -> Files:
    common = {
        "serviceKey": settings.data_go_kr_key,
        "resultType": "json",
        "numOfRows": MAX_ROWS,
        "pageNo": 1,
    }
    items = fsc_json(
        "fsc_items.json",
        http.get(
            fsc.ITEM_URL,
            params={
                **common,
                "likeItmsNm": "삼성전자",
                "beginBasDt": ymd(today - timedelta(days=fsc.ITEM_LOOKBACK_DAYS)),
            },
        ),
    )
    prices = fsc_json(
        "fsc_prices.json",
        http.get(
            fsc.PRICE_URL,
            params={
                **common,
                "likeSrtnCd": STOCK_CODE,
                "beginBasDt": ymd(today - timedelta(days=14)),
            },
        ),
    )
    return {"fsc_items.json": as_json(items), "fsc_prices.json": as_json(prices)}


# 소스 이름 → (필요한 키의 환경변수 이름, Settings 속성, 녹화 함수)
SOURCES: dict[str, tuple[str, str, Callable[[httpx.Client, Settings, date], Files]]] = {
    "dart": ("DART_API_KEY", "dart_api_key", record_dart),
    "dart_reports": ("DART_API_KEY", "dart_api_key", record_dart_reports),
    "fsc": ("DATA_GO_KR_KEY", "data_go_kr_key", record_fsc),
}


def load_manifest() -> dict:
    if not MANIFEST.exists():
        return {"max_rows": MAX_ROWS, "sources": {}}
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest.setdefault("sources", {})
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="실제 API 응답을 tests/fixtures/에 녹화한다.")
    parser.add_argument("--only", choices=sorted(SOURCES), help="이 소스만 녹화한다")
    parser.add_argument("--force", action="store_true", help="이미 녹화한 소스도 다시 받는다")
    args = parser.parse_args()

    manifest = load_manifest()
    settings = load_settings()
    today = now_kst().date()
    failed = False

    with httpx.Client(timeout=30.0) as http:
        for name in [args.only] if args.only else list(SOURCES):
            env_name, attr, record = SOURCES[name]
            if name in manifest["sources"] and not args.force:
                print(f"[{name}] 이미 녹화돼 있습니다. 다시 받으려면 --force를 붙이세요.")
                continue
            secret = getattr(settings, attr)
            if not secret:
                print(f"[{name}] {env_name}가 없어 건너뜁니다.", file=sys.stderr)
                failed = True
                continue
            try:
                files = record(http, settings, today)
            except httpx.TransportError as exc:
                # 예외 문자열에 요청 URL(키 포함)이 섞일 수 있어 종류만 남긴다.
                print(
                    f"[{name}] 연결 실패({type(exc).__name__}). 파일은 그대로 둡니다. "
                    "이 네트워크에서 접속이 막혀 있을 수 있습니다.",
                    file=sys.stderr,
                )
                failed = True
                continue
            except RecordError as exc:
                # 오류 응답이 요청 값을 되돌려 줄 수 있어 키는 가리고 출력한다.
                print(f"[{name}] 저장하지 않음: {str(exc).replace(secret, '***')}", file=sys.stderr)
                failed = True
                continue
            if any(secret.encode() in content for content in files.values()):
                print(f"[{name}] 응답에 API 키가 들어 있어 저장하지 않습니다.", file=sys.stderr)
                failed = True
                continue
            for filename, content in files.items():
                (FIXTURES / filename).write_bytes(content)
                print(f"[{name}] 저장: {filename}")
            if name == "fsc":
                print("[fsc] 실제 시세는 재배포할 수 없습니다. 이 파일들은 커밋하지 마세요.")
            manifest["sources"][name] = {"recorded_on": today.isoformat()}
            MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")

    missing = [name for name in SOURCES if name not in manifest["sources"]]
    if missing:
        print(f"아직 샘플 값인 소스: {', '.join(missing)}")
    print("끝. 기대값을 고친 뒤 uv run pytest로 확인하세요.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
