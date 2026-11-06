from backend.downloads.cache_keys import build_media_key, source_identity_hash


def test_media_key_is_deterministic_for_same_identity() -> None:
    first = build_media_key(
        platform="youtube",
        source_id="dQw4w9WgXcQ",
        output_profile="free-480p",
        processing_version="1",
    )
    second = build_media_key(
        platform="youtube",
        source_id="dQw4w9WgXcQ",
        output_profile="free-480p",
        processing_version="1",
    )

    assert first == second
    assert len(first) == 64


def test_media_key_changes_with_entitlement_profile() -> None:
    free_key = build_media_key(
        platform="youtube",
        source_id="dQw4w9WgXcQ",
        output_profile="free-480p",
        processing_version="1",
    )
    premium_key = build_media_key(
        platform="youtube",
        source_id="dQw4w9WgXcQ",
        output_profile="premium-2160p",
        processing_version="1",
    )

    assert free_key != premium_key


def test_media_key_changes_with_processing_version() -> None:
    first = build_media_key(
        platform="youtube",
        source_id="dQw4w9WgXcQ",
        output_profile="free-480p",
        processing_version="1",
    )
    second = build_media_key(
        platform="youtube",
        source_id="dQw4w9WgXcQ",
        output_profile="free-480p",
        processing_version="2",
    )

    assert first != second


def test_source_identity_hash_is_stable() -> None:
    assert source_identity_hash("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == (
        source_identity_hash("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    )
    assert source_identity_hash("https://www.youtube.com/watch?v=dQw4w9WgXcQ") != (
        source_identity_hash("https://www.youtube.com/watch?v=AAAAAAAAAAA")
    )
