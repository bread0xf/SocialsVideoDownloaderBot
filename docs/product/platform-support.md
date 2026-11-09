# Platform Support Matrix

**MVP target:** TikTok, Instagram, YouTube and Facebook. Support is conditional on public accessibility, platform policy, extractor capability and current technical constraints.

| Platform | MVP status | Accepted content | Explicit exclusions |
|---|---|---|---|
| TikTok | Live-verified 2026-11-06 | Public video URL | Private/restricted videos, login-required content |
| Instagram | Live-verified 2026-11-06 | Public Reel/video URL | Private accounts, Stories requiring authentication, login-required content |
| YouTube | Live-verified 2026-11-06 | Public individual video URL | Playlists, channels, live streams, age/restriction bypass |
| Facebook | Live-verified 2026-11-06 | Public individual video URL | Private/group-restricted content, login-required content |

Live metadata, download and FFmpeg preparation passed for one public sample per platform. YouTube requires `yt-dlp-ejs` with a Deno 2.3+ runtime. Some older Facebook URLs fail in yt-dlp with `Cannot parse data`; that is an extractor limitation, not a URL-normalization issue. Platform availability can change without notice.

## URL handling

**Implemented:** exact host/path validation, canonicalization, tracking-query stripping, IP/localhost/credential/port rejection, DNS global-address checks at ingestion, and validation of the final extracted URL against the platform allowlist. **Pending:** controlled egress or a network policy for full DNS-rebinding protection.

- Require `https` by default. If `http` is accepted for a platform redirect, upgrade safely and validate the destination.
- Parse and normalize hostnames; reject lookalike domains and unexpected ports.
- Use exact host allowlists and platform-specific path validators.
- Do not accept arbitrary URLs simply because yt-dlp can parse them.
- Follow redirects only through a controlled validation layer; revalidate every redirect destination.
- Reject URLs resolving to loopback, private, link-local, multicast, reserved or internal infrastructure addresses.
- Strip tracking parameters only where doing so does not change content identity.
- Store a privacy-conscious normalized source identifier, not unnecessary query strings.

## Extraction interface

Platform adapters should implement a common interface, for example:

```python
class PlatformAdapter(Protocol):
    def can_handle(self, normalized_url: NormalizedURL) -> bool: ...
    async def inspect(self, normalized_url: NormalizedURL) -> MediaMetadata: ...
    async def download(
        self,
        normalized_url: NormalizedURL,
        profile: OutputProfile,
        workspace: JobWorkspace,
    ) -> DownloadArtifact: ...
```

The exact signatures may evolve, but application/domain code must not depend directly on yt-dlp internals.

## Format selection

- Free: select the best available format at or below the locked Free ceiling (480p).
- Premium: select the best practical available quality up to 4K, subject to source, codec, file size, processing and Telegram delivery constraints.
- If the requested entitlement cannot be satisfied, choose a documented fallback or fail clearly; do not silently exceed plan limits.
- No manual quality selector in MVP.

## Platform reliability

Extraction support can change when platforms change their delivery mechanisms. Implement:
- Adapter-level timeouts and bounded retries.
- Platform-specific error classification.
- Version pinning and controlled yt-dlp updates.
- Fixture-based regression tests that do not redistribute copyrighted media.
- A feature flag to disable a platform quickly.
- Monitoring by platform and extractor version.

## Legal and policy review

Before launch, review platform terms, applicable copyright law, user rights, and Telegram rules. Public visibility does not automatically grant redistribution rights. Provide a takedown/contact process and avoid claims that the service is endorsed by any platform.
