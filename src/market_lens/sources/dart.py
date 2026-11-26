"""DART OpenAPI 클라이언트: 고유번호(corp_code), 공시 목록, 공시 원문, 주요 재무계정.

공식 문서: https://opendart.fss.or.kr/guide/main.do
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from typing import Any
from xml.etree import ElementTree

from ..cache import TTL_DISCLOSURE_LIST, TTL_LONG, TTL_REFERENCE
from ..errors import NotFoundError, SourceError
from ..util import clean_stock_code, is_stock_code, norm_name, to_int, ymd_to_iso
from ._base import BaseSource, Fetched

BASE_URL = "https://opendart.fss.or.kr/api"
SOURCE = "DART OpenAPI (금융감독원 전자공시시스템)"
VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

DISCLOSURE_TYPES = {
    "A": "정기공시",
    "B": "주요사항보고",
    "C": "발행공시",
    "D": "지분공시",
    "E": "기타공시",
    "F": "외부감사관련",
    "G": "펀드공시",
    "H": "자산유동화",
    "I": "거래소공시",
    "J": "공정위공시",
}
# 분기 → 보고서 코드 (1분기보고서, 반기보고서, 3분기보고서, 사업보고서)
REPORT_CODES = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}

STATUS_OK = "000"
STATUS_NO_DATA = "013"
PAGE_SIZE = 100


def _check_status(status: str | None, message: str | None) -> None:
    if status not in (STATUS_OK, STATUS_NO_DATA):
        raise SourceError(f"DART 오류 {status}: {message}")


def _unzip(content: bytes) -> dict[str, bytes]:
    """ZIP 응답을 푼다. 오류일 때 DART는 ZIP 대신 status/message XML을 돌려준다."""
    if not zipfile.is_zipfile(io.BytesIO(content)):
        text = content.decode("utf-8", errors="replace")
        status = re.search(r"<status>(.*?)</status>", text)
        message = re.search(r"<message>(.*?)</message>", text)
        if status:
            if status.group(1) == STATUS_NO_DATA:
                raise NotFoundError("DART에 해당 자료가 없습니다.")
            raise SourceError(f"DART 오류 {status.group(1)}: {message.group(1) if message else ''}")
        raise SourceError("DART 응답을 해석할 수 없습니다(ZIP이 아님).")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# 닫힐 때 줄을 바꾸는 태그. DART 전용 서식(dart4.xsd)의 표지·제목 태그를 포함한다.
_BLOCK_TAGS = (
    r"p|tr|table|table-group|title|cover-title|document-name|company-name|"
    r"div|li|h\d|section[^>]*"
)


def document_to_text(markup: str) -> str:
    """DART 공시 원문(XML/HTML 혼합 마크업)에서 본문 텍스트만 남긴다."""
    # 서식 버전, 추출용 요약 같은 머리 정보는 본문이 아니다.
    text = re.sub(r"(?is)<(style|script|formula-version|summary)\b.*?</\1>", " ", markup)
    # 원문은 표의 칸마다 줄을 바꿔 적는다. 줄바꿈은 태그로만 정해 한 행이 한 줄이 되게 한다.
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(rf"(?i)</({_BLOCK_TAGS})>|<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(td|th|te|tu)>", " | ", text)
    text = re.sub(r"(?s)<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line and set(line) - {"|", " "})


def _disclosure(row: dict[str, Any]) -> dict[str, Any]:
    """list.json 한 행 → models.Disclosure 필드."""
    return {
        "rcept_no": row["rcept_no"],
        "title": (row.get("report_nm") or "").strip(),
        "date": ymd_to_iso(row.get("rcept_dt", "")),
        "filer": row.get("flr_nm", ""),
        "corp_name": row.get("corp_name", ""),
        "remark": row.get("rm", "") or "",
        "url": VIEWER_URL.format(rcept_no=row["rcept_no"]),
    }


def _account(row: dict[str, Any]) -> dict[str, Any]:
    """fnlttSinglAcnt.json 한 행 → 계정 한 줄. 금액은 정수(원)로 바꾼다."""
    return {
        "name": row.get("account_nm", ""),
        "consolidated": row.get("fs_div") == "CFS",
        "statement": row.get("fs_nm"),
        "is_income": row.get("sj_div") == "IS",
        "current": to_int(row.get("thstrm_amount")),
        "current_period": row.get("thstrm_dt"),
        "prior": to_int(row.get("frmtrm_amount")),
        "prior_period": row.get("frmtrm_dt"),
        "cumulative": to_int(row.get("thstrm_add_amount")),
        "prior_cumulative": to_int(row.get("frmtrm_add_amount")),
        "currency": row.get("currency"),
        "rcept_no": row.get("rcept_no"),
    }


class DartClient(BaseSource):
    name = "DART"

    async def corp_index(self) -> Fetched:
        """상장사 고유번호 목록: [{corp_code, corp_name, stock_code}]."""

        async def load() -> list[dict[str, str]]:
            response = await self._get(f"{BASE_URL}/corpCode.xml", {"crtfc_key": self._key})
            files = _unzip(response.content)
            root = ElementTree.fromstring(next(iter(files.values())))
            corps = []
            for node in root.iter("list"):
                stock_code = (node.findtext("stock_code") or "").strip()
                if stock_code:  # 비상장사는 제외
                    corps.append(
                        {
                            "corp_code": (node.findtext("corp_code") or "").strip(),
                            "corp_name": (node.findtext("corp_name") or "").strip(),
                            "stock_code": stock_code,
                        }
                    )
            if not corps:
                raise SourceError("DART 고유번호 목록이 비어 있습니다.")
            return corps

        return await self._cached("dart:corp_index", TTL_REFERENCE, load)

    async def find_corp(self, query: str) -> tuple[dict[str, str] | None, list[dict[str, str]]]:
        """종목코드 또는 회사명으로 찾는다. (정확히 일치한 회사, 부분 일치 후보)를 돌려준다."""
        corps = (await self.corp_index()).value
        if is_stock_code(query):
            code = clean_stock_code(query)
            exact = [c for c in corps if c["stock_code"] == code]
            return (exact[0] if exact else None), []
        target = norm_name(query.strip())
        exact = [c for c in corps if norm_name(c["corp_name"]) == target]
        partial = [c for c in corps if target in norm_name(c["corp_name"])]
        partial.sort(key=lambda c: len(c["corp_name"]))
        return (exact[0] if exact else None), partial[:10]

    async def list_disclosures(
        self, corp_code: str, begin: str, end: str, kind: str | None, limit: int
    ) -> Fetched:
        """공시 목록(최신순): {total_count, items: [Disclosure 필드]}. begin/end는 YYYYMMDD."""

        async def load() -> dict[str, Any]:
            items: list[dict[str, Any]] = []
            total = 0
            page = 1
            while len(items) < limit:
                params = {
                    "crtfc_key": self._key,
                    "corp_code": corp_code,
                    "bgn_de": begin,
                    "end_de": end,
                    "page_no": page,
                    "page_count": PAGE_SIZE,
                }
                if kind:
                    params["pblntf_ty"] = kind
                payload = self._json(await self._get(f"{BASE_URL}/list.json", params))
                total = int(payload.get("total_count") or 0)
                items.extend(payload.get("list") or [])
                if page >= int(payload.get("total_page") or 1):
                    break
                page += 1
            return {"total_count": total, "items": items[:limit]}

        key = f"dart:list:{corp_code}:{begin}:{end}:{kind or '-'}:{limit}"
        listing = await self._cached(key, TTL_DISCLOSURE_LIST, load)
        return listing.map(lambda v: {**v, "items": [_disclosure(row) for row in v["items"]]})

    async def document_text(self, rcept_no: str) -> Fetched:
        """공시 원문 전체 텍스트. 첨부가 여러 개면 본문(접수번호.xml)을 고른다."""

        async def load() -> str:
            response = await self._get(
                f"{BASE_URL}/document.xml", {"crtfc_key": self._key, "rcept_no": rcept_no}
            )
            files = _unzip(response.content)
            if not files:
                raise NotFoundError(f"접수번호 {rcept_no}의 원문 파일이 없습니다.")
            main = next(
                (data for name, data in files.items() if name.startswith(f"{rcept_no}.")),
                max(files.values(), key=len),
            )
            return document_to_text(_decode(main))

        return await self._cached(f"dart:doc:{rcept_no}", TTL_LONG, load)

    async def financials(self, corp_code: str, year: int, quarter: int) -> Fetched:
        """단일회사 주요계정(fnlttSinglAcnt)의 계정 목록. 자료가 없으면 빈 목록."""

        async def load() -> list[dict[str, Any]]:
            params = {
                "crtfc_key": self._key,
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": REPORT_CODES[quarter],
            }
            payload = self._json(await self._get(f"{BASE_URL}/fnlttSinglAcnt.json", params))
            return payload.get("list") or []

        key = f"dart:fin:{corp_code}:{year}:{quarter}"
        # 아직 제출되지 않은 분기(빈 응답)는 캐시하지 않는다
        rows = await self._cached(key, TTL_LONG, load, keep=bool)
        return rows.map(lambda v: [_account(row) for row in v])

    @staticmethod
    def _json(response: Any) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            raise SourceError(
                f"DART 응답을 해석할 수 없습니다(HTTP {response.status_code})."
            ) from None
        _check_status(payload.get("status"), payload.get("message"))
        return payload
