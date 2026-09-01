from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest

from aegisquant.data.models import ProviderAccessState
from aegisquant.data.provider_registry import ProviderRegistry, SourcePolicyRegistry
from aegisquant.domain.errors import DomainError
from aegisquant.domain.identifiers import ProviderId, SourcePolicyId
from aegisquant.domain.intelligence import ContentType, RightsState
from aegisquant.intelligence.collectors import (
    SOURCE_CONTRACTS,
    BlueskyStreamSelection,
    OfficialSourceAdapter,
    SourceKind,
    SourceQuotaWindow,
    awaiting_credentials_batch,
    build_source_request,
    content_contracts,
    parse_bluesky_jetstream,
    parse_gdelt,
    parse_github,
    parse_github_webhook,
    parse_rss_atom,
    parse_telegram_bot,
    parse_x,
    parse_youtube,
    select_bluesky_transport,
    snapshot_official_web_change,
)

NOW = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.mark.parametrize("source", [SourceKind.X, SourceKind.TELEGRAM_BOT, SourceKind.YOUTUBE])
def test_credentialed_sources_are_explicitly_awaiting(source: SourceKind) -> None:
    contract = SOURCE_CONTRACTS[source]
    assert contract.credentials_required is True
    assert contract.access_state is ProviderAccessState.AWAITING_CREDENTIALS
    assert (
        awaiting_credentials_batch(source).access_state is ProviderAccessState.AWAITING_CREDENTIALS
    )


def test_registry_reports_awaiting_credentials_before_collection(project_root: Path) -> None:
    providers = ProviderRegistry.from_yaml(project_root / "data/catalogs/provider_registry.yaml")
    policies = SourcePolicyRegistry.from_yaml(
        project_root / "data/catalogs/source_policy_registry.yaml"
    )
    policy = policies.get(SourcePolicyId("x_official_restricted_v1"))
    with pytest.raises(DomainError, match="AQ-PROVIDER-ACCESS-AWAITING_CREDENTIALS"):
        providers.require_collection(ProviderId("x_official"), policy)


def test_request_contracts_work_without_secrets_but_cannot_execute() -> None:
    request = build_source_request(
        SourceKind.X,
        "recent_search",
        {"query": "bitcoin", "max_results": 10},
    )
    assert request.access_state is ProviderAccessState.AWAITING_CREDENTIALS
    assert request.executable is False
    assert "secret" not in request.model_dump_json().casefold()
    assert set(SOURCE_CONTRACTS[SourceKind.X].endpoints) == {
        "filtered_stream",
        "recent_search",
        "full_archive_search",
    }
    with pytest.raises(ValueError, match="PLAINTEXT-CREDENTIAL-DENIED"):
        build_source_request(
            SourceKind.YOUTUBE,
            "videos",
            {"part": "snippet", "api_key": "synthetic-denied-value"},  # pragma: allowlist secret
        )


def test_source_quota_window_fails_closed_when_mock_budget_is_exhausted() -> None:
    quota = SourceQuotaWindow(
        source=SourceKind.X,
        window_start=NOW,
        reset_time=datetime(2026, 9, 2, tzinfo=UTC),
        limit=2,
        used=0,
        unit="posts",
    )
    quota = quota.consume().consume()
    assert quota.used == 2
    with pytest.raises(ValueError, match="QUOTA-EXHAUSTED"):
        quota.consume()


def test_public_source_requests_are_allowlisted_and_executable() -> None:
    requests = (
        build_source_request(SourceKind.RSS_ATOM, "federal_reserve"),
        build_source_request(
            SourceKind.GDELT,
            "doc",
            {"query": "bitcoin", "mode": "artlist", "format": "json"},
        ),
        build_source_request(
            SourceKind.GITHUB,
            "releases",
            {"owner": "example", "repo": "protocol"},
        ),
    )
    assert all(item.access_state is ProviderAccessState.READY for item in requests)
    assert all(item.executable is True for item in requests)


def test_official_source_adapter_rejects_credentialled_client_before_network() -> None:
    def fail_if_called(_: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be called")

    with httpx.Client(
        headers={"Authorization": "x"}, transport=httpx.MockTransport(fail_if_called)
    ) as client:
        adapter = OfficialSourceAdapter(SourceKind.RSS_ATOM, client)
        with pytest.raises(ValueError, match="CREDENTIALLED-CLIENT-DENIED"):
            adapter.fetch_text("federal_reserve")


def test_rss_gdelt_x_and_content_contracts_parse_fixtures(
    project_root: Path, event_fixtures: dict[str, object]
) -> None:
    rss = parse_rss_atom(
        (project_root / "tests/fixtures/p04/rss_atom.xml").read_bytes(),
        observed_time=NOW,
        capability="federal_reserve",
    )
    gdelt = parse_gdelt(cast(dict[str, object], event_fixtures["gdelt"]), observed_time=NOW)
    x_posts = parse_x(cast(dict[str, object], event_fixtures["x"]), observed_time=NOW)
    assert rss[0].content_type is ContentType.ANNOUNCEMENT
    assert gdelt[0].verified_source is False
    assert x_posts[0].revision == 2
    assert x_posts[0].engagement["like_count"] == 10
    identity, envelope, engagement = content_contracts(
        x_posts[0],
        available_time=NOW,
        ingest_time=NOW,
        source_policy_id=SourcePolicyId("x_official_restricted_v1"),
        rights_state=RightsState.LIMITED,
    )
    assert identity.verified is True
    assert envelope.revision == 2
    assert engagement is not None and engagement.metrics["retweet_count"] == 4
    assert envelope.engagement_snapshot_id == engagement.engagement_snapshot_id


def test_telegram_enforces_authorized_channels(event_fixtures: dict[str, object]) -> None:
    payload = cast(dict[str, object], event_fixtures["telegram"])
    parsed = parse_telegram_bot(
        payload, observed_time=NOW, allowed_channel_ids=frozenset({"-100123"})
    )
    assert parsed[0].revision == 2
    with pytest.raises(ValueError, match="CHANNEL-NOT-ALLOWLISTED"):
        parse_telegram_bot(payload, observed_time=NOW, allowed_channel_ids=frozenset())


def test_bluesky_github_and_youtube_parse_official_contract_shapes(
    event_fixtures: dict[str, object],
) -> None:
    bluesky = parse_bluesky_jetstream(
        cast(dict[str, object], event_fixtures["bluesky_create"]), observed_time=NOW
    )
    release = parse_github(
        cast(dict[str, object], event_fixtures["github_release"]),
        observed_time=NOW,
        capability="releases",
    )
    advisory = parse_github(
        cast(dict[str, object], event_fixtures["github_advisory"]),
        observed_time=NOW,
        capability="security_advisories",
    )
    youtube = parse_youtube(
        cast(dict[str, object], event_fixtures["youtube"]),
        observed_time=NOW,
        capability="videos",
    )
    assert bluesky[0].checkpoint == "1788112800000000"
    assert release[0].content_type is ContentType.RELEASE
    assert advisory[0].content_type is ContentType.ANNOUNCEMENT
    assert youtube[0].content_type is ContentType.VIDEO_META


def test_x_deletion_and_bluesky_delete_are_explicit_revisions() -> None:
    x_deleted = parse_x(
        {
            "data": {
                "id": "deleted-post-1",
                "author_id": "author-1",
                "created_at": "2026-08-30T18:00:00Z",
                "deleted": True,
                "edit_history_tweet_ids": ["deleted-post-1"],
            },
            "includes": {"users": []},
        },
        observed_time=NOW,
    )[0]
    bluesky_deleted = parse_bluesky_jetstream(
        {
            "did": "did:plc:fixture123",
            "time_us": 1788112800000000,
            "commit": {
                "operation": "delete",
                "collection": "app.bsky.feed.post",
                "rkey": "3fixture",
            },
        },
        observed_time=NOW,
    )[0]
    assert x_deleted.text == "[deleted]" and x_deleted.deleted_time == NOW
    assert bluesky_deleted.revision == 2 and bluesky_deleted.deleted_time == NOW


def test_xml_dtd_and_entity_declarations_are_rejected() -> None:
    payload = b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'
    with pytest.raises(ValueError, match="XML-UNSAFE"):
        parse_rss_atom(payload, observed_time=NOW, capability="federal_reserve")


def test_official_web_change_is_hash_versioned_and_host_allowlisted() -> None:
    first = snapshot_official_web_change(
        source_native_id="federal_reserve",
        canonical_url="https://www.federalreserve.gov/newsevents.htm",
        content=b"version one",
        observed_time=NOW,
    )
    second = snapshot_official_web_change(
        source_native_id="federal_reserve",
        canonical_url="https://www.federalreserve.gov/newsevents.htm",
        content=b"version two",
        observed_time=NOW,
        previous_sha256=first.content_sha256,
    )
    assert first.changed is False
    assert second.changed is True
    with pytest.raises(ValueError, match="HOST-NOT-ALLOWLISTED"):
        snapshot_official_web_change(
            source_native_id="evil",
            canonical_url="https://example.invalid/source",
            content=b"x",
            observed_time=NOW,
        )


def test_bluesky_detects_contract_and_falls_back_to_firehose() -> None:
    compatible: BlueskyStreamSelection = select_bluesky_transport(
        detected_event_fields=frozenset({"did", "time_us", "kind", "commit"}),
        jetstream_available=True,
    )
    fallback = select_bluesky_transport(
        detected_event_fields=frozenset({"did", "time_us"}), jetstream_available=True
    )
    assert compatible.mode == "JETSTREAM" and compatible.fallback_used is False
    assert fallback.mode == "FIREHOSE" and fallback.fallback_used is True
    assert fallback.checkpoint_parameter == "cursor"


def test_github_webhook_requires_verified_signature() -> None:
    payload = {
        "repository": {
            "full_name": "example/protocol",
            "html_url": "https://github.com/example/protocol",
        },
        "action": "opened",
    }
    with pytest.raises(ValueError, match="SIGNATURE-NOT-VERIFIED"):
        parse_github_webhook(
            payload,
            observed_time=NOW,
            event_name="issues",
            delivery_id="delivery-1",
            signature_verified=False,
        )
    parsed = parse_github_webhook(
        payload,
        observed_time=NOW,
        event_name="issues",
        delivery_id="delivery-1",
        signature_verified=True,
    )
    assert parsed[0].checkpoint == "delivery-1"


def test_youtube_authorized_live_chat_is_a_channel_message() -> None:
    payload = {
        "items": [
            {
                "id": "chat-message-1",
                "snippet": {
                    "publishedAt": "2026-09-01T00:00:00Z",
                    "displayMessage": "Protocol upgrade briefing",
                },
                "authorDetails": {
                    "channelId": "channel-1",
                    "displayName": "Authorized Channel",
                    "isVerified": True,
                },
            }
        ]
    }
    parsed = parse_youtube(payload, observed_time=NOW, capability="live_chat")
    assert parsed[0].content_type is ContentType.CHANNEL_MESSAGE
