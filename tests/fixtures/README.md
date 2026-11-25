# 테스트 픽스처

공식 API 문서의 응답 형식에 맞춰 만든 **샘플**입니다. 필드 이름과 구조는 실제 응답과 같지만 금액, 주가, 공시 제목은 지어낸 값이며 실제 수치가 아닙니다.

실제 응답으로 바꾸려면 저장소 루트에서 `uv run python scripts/record_fixtures.py`를 실행하세요. API 키는 응답 본문에 들어가지 않으므로 파일에 남지 않습니다.

| 파일 | API |
| --- | --- |
| `dart_corpcode.xml` | DART `corpCode.xml` (ZIP 안의 `CORPCODE.xml`, 일부 회사만) |
| `dart_list.json` | DART `list.json` |
| `dart_document.xml` | DART `document.xml` (ZIP 안의 원문) |
| `dart_financials.json` | DART `fnlttSinglAcnt.json` (3분기보고서) |
| `fsc_items.json` | 금융위원회 KRX상장종목정보 `getItemInfo` |
| `fsc_prices.json` | 금융위원회 주식시세정보 `getStockPriceInfo` |
