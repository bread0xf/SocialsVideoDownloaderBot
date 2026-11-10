from pathlib import Path
from types import SimpleNamespace
from typing import cast

from telegram import Bot, InputFile

from backend.delivery.telegram import BotDelivery
from backend.media.ffprobe import ProbeResult
from backend.media.processing import PreparedMedia


class _FakeBot:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    async def send_video(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = kwargs
        return SimpleNamespace(message_id=7, video=SimpleNamespace(file_id="file-id"))


async def test_send_video_uploads_file_bytes(tmp_path: Path) -> None:
    payload = b"\x00\x00\x00 ftypisom-fake-mp4"
    path = tmp_path / "output.mp4"
    path.write_bytes(payload)
    media = PreparedMedia(
        path=path,
        probe=ProbeResult(
            duration_seconds=12.0,
            width=854,
            height=480,
            video_codec="h264",
            audio_codec="aac",
            format_name="mp4",
            size_bytes=len(payload),
        ),
        mime_type="video/mp4",
    )
    bot = _FakeBot()
    delivery = BotDelivery(cast(Bot, bot))

    result = await delivery.send_video(123, media, caption="test", filename="youtube-abc123.mp4")

    assert result.message_id == 7
    assert result.file_id == "file-id"
    assert bot.kwargs is not None
    video = bot.kwargs["video"]
    assert isinstance(video, InputFile)
    assert video.input_file_content == payload
    assert video.filename == "youtube-abc123.mp4"
    assert video.mimetype == "video/mp4"
