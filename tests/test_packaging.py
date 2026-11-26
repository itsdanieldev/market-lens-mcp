"""패키지 메타데이터가 서로 어긋나지 않는지 검증한다."""

from __future__ import annotations

import tomllib
from pathlib import Path

import market_lens

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_matches_pyproject():
    """pyproject.toml의 버전과 market_lens.__version__이 같다(릴리스 태그가 이 값을 따른다)."""
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert project["version"] == market_lens.__version__


def test_no_personal_authors_in_metadata():
    """배포 메타데이터의 작성자는 개인이 아니라 프로젝트 기여자 전체다."""
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert project["authors"] == [{"name": "market-lens-mcp contributors"}]
