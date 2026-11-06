import hashlib


def build_media_key(
    *,
    platform: str,
    source_id: str,
    output_profile: str,
    processing_version: str,
) -> str:
    material = "\x1f".join((platform, source_id, output_profile, processing_version))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def source_identity_hash(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
