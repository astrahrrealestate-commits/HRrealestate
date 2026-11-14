"""Download a pinned CTranslate2 model: `python -m app.translation.fetch DIR [nl-en|en-nl]` (image build,
`make translation-model`).

Files are fetched from one fixed Hugging Face revision and checked against their SHA-256, so a build can never pick
up a changed model silently. Both directions are Helsinki-NLP OPUS-MT (CC-BY-4.0) converted by third parties; the
hashes were taken from a one-time download and review of the files.
"""

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True)
class ModelSpec:
    repo: str
    revision: str
    files: dict[str, str]  # name -> sha256


MODELS: dict[str, ModelSpec] = {
    "nl-en": ModelSpec(
        repo="gaudi/opus-mt-nl-en-ctranslate2",
        revision="b3cf3a61c0c3a7e2628813dfb0f2049046045aa1",
        files={
            "config.json": "ce02c0c0d02f285d2ff34c80b0867ccb5c4a3b250a275e6d1d2884f5499a6e46",
            "model.bin": "a07b5103b41acba9c3ae718f75c2f6031d9f497075bcd903c1015ceaede2e8de",
            "shared_vocabulary.json": "78c1ea4f71b7d582051c7250032d2d959e60c5d42078f5d540951153ad836774",
            "source.spm": "f538d23d4b30641cd97c608d2a83890d503aa1286a5560f19ef949404a786e94",
            "target.spm": "d05781fde84b8793191528a7a176e1b17f96265388f602379ee6ae3139f59141",
        },
    ),
    "en-nl": ModelSpec(
        repo="manancode/opus-mt-en-nl-ctranslate2-android",
        revision="62819eb9d036d4271f23a4b480c1f05a5df66181",
        files={
            "config.json": "8f6496adfc930cbfecbe8281112197705c488fab47d34b4829b06d7f478909af",
            "model.bin": "6399213f6bf2144d766438c6703e03126eaec562e91ed5d3be31e26180bd830c",
            "shared_vocabulary.json": "78c1ea4f71b7d582051c7250032d2d959e60c5d42078f5d540951153ad836774",
            "source.spm": "d05781fde84b8793191528a7a176e1b17f96265388f602379ee6ae3139f59141",
            "target.spm": "f538d23d4b30641cd97c608d2a83890d503aa1286a5560f19ef949404a786e94",
        },
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(target: Path, direction: str = "nl-en") -> None:
    """Fill `target` with the model; files that are already there and match are left alone."""
    spec = MODELS[direction]
    target.mkdir(parents=True, exist_ok=True)
    for name, expected in spec.files.items():
        path = target / name
        if path.is_file() and _sha256(path) == expected:
            continue
        url = f"https://huggingface.co/{spec.repo}/resolve/{spec.revision}/{name}"
        with httpx.stream("GET", url, follow_redirects=True, timeout=300) as response:
            response.raise_for_status()
            with path.open("wb") as handle:
                for chunk in response.iter_bytes(1 << 20):
                    handle.write(chunk)
        if _sha256(path) != expected:
            path.unlink()
            raise SystemExit(f"{name}: checksum mismatch, refusing to use it")


if __name__ == "__main__":
    fetch(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "nl-en")
