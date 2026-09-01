from __future__ import annotations

import pytest

from aegisquant.intelligence.static_analysis.discovery import normalize_public_candidates


def test_public_discovery_is_metadata_only_and_deterministic() -> None:
    records = (
        {
            "platform": "joinquant",
            "url": "https://www.joinquant.com/view/community/detail/42#fragment",
            "title": "候选",
            "author": "公开索引作者",
            "summary": "仅公开搜索摘要",
            "keywords": ["trend", "trend"],
        },
    )
    first = normalize_public_candidates(records)
    second = normalize_public_candidates(records)
    assert first == second
    assert first[0].content_fetch_allowed is False
    assert first[0].access_bypass_allowed is False
    assert first[0].url == "https://www.joinquant.com/view/community/detail/42"
    assert first[0].keywords == ("trend",)


def test_public_discovery_rejects_secret_query_and_unapproved_host() -> None:
    with pytest.raises(ValueError, match="secret-like"):
        normalize_public_candidates(
            ({"platform": "joinquant", "url": "https://joinquant.com/a?token=x", "title": "x"},)
        )
    with pytest.raises(ValueError, match="approved platform host"):
        normalize_public_candidates(
            ({"platform": "other", "url": "https://example.com/a", "title": "x"},)
        )
