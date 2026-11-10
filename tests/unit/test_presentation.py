from backend.delivery.presentation import build_caption, build_filename, platform_name


def test_build_caption_includes_title_uploader_and_quality() -> None:
    caption = build_caption(
        platform="youtube",
        title="Example video",
        uploader="Example Channel",
        height=480,
    )

    assert caption == "<b>Example video</b>\n<i>by Example Channel</i>\nYouTube · 480p"


def test_build_caption_omits_missing_metadata() -> None:
    assert build_caption(platform="tiktok") == "TikTok"


def test_build_caption_escapes_html() -> None:
    caption = build_caption(
        platform="instagram",
        title="<script>&",
        uploader="<b>creator</b>",
        height=480,
    )

    assert "&lt;script&gt;&amp;" in caption
    assert "&lt;b&gt;creator&lt;/b&gt;" in caption
    assert "<script>" not in caption


def test_build_caption_stays_within_telegram_limit() -> None:
    caption = build_caption(platform="youtube", title="x" * 500, height=480)

    assert len(caption) <= 1024


def test_build_filename_uses_platform_and_source_id() -> None:
    assert build_filename("youtube", "dQw4w9WgXcQ") == "youtube-dQw4w9WgXcQ.mp4"
    assert build_filename("tiktok", "7704346827457416456") == ("tiktok-7704346827457416456.mp4")


def test_build_filename_sanitizes_unsafe_source_ids() -> None:
    assert build_filename("facebook", "../../etc/passwd") == "facebook-etc-passwd.mp4"
    assert build_filename("instagram", "///") == "instagram-video.mp4"


def test_platform_name_falls_back_to_a_readable_label() -> None:
    assert platform_name("youtube") == "YouTube"
    assert platform_name("some_new_platform") == "Some New Platform"
