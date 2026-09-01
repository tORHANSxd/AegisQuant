from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from aegisquant.intelligence.static_analysis.models import (
    ArtifactKind,
    KnowledgePlatform,
    RightsRecord,
    RightsStatus,
    SourceManifest,
)

NOW = datetime(2026, 9, 2, tzinfo=UTC)


def test_rights_unknown_cannot_export_public_text() -> None:
    with pytest.raises(ValidationError, match="public-license"):
        RightsRecord(
            source_id="unknown-source",
            status=RightsStatus.UNKNOWN,
            public_text_export_allowed=True,
            internal_research_allowed=True,
            reviewed_at_utc=NOW,
        )


def test_manual_source_manifest_rejects_missing_user_access() -> None:
    with pytest.raises(ValidationError, match="user_had_access"):
        SourceManifest.model_validate(
            {
                "source_id": "jq-test",
                "platform": KnowledgePlatform.JOINQUANT,
                "url": "https://www.joinquant.com/test",
                "title": "test",
                "author": "author",
                "exported_at_utc": NOW,
                "export_method": "manual",
                "user_had_access": False,
                "content_types": (ArtifactKind.PYTHON,),
                "rights_status": RightsStatus.UNKNOWN,
                "original_language": "zh-CN",
            }
        )
