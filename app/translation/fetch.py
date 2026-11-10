"""Download the pinned CTranslate2 model: `python -m app.translation.fetch DIR` (image build, `make translation-model`).

Files are fetched from one fixed Hugging Face revision and checked against their SHA-256, so a build can never pick
up a changed model silently. Helsinki-NLP/opus-mt-nl-en, CC-BY-4.0, converted by `gaudi/opus-mt-nl-en-ctranslate2`.
"""

import hashlib
import sys
from pathlib import Path

import httpx

REPO = "gaudi/opus-mt-nl-en-ctranslate2"
REVISION = "b3cf3a61c0c3a7e2628813dfb0f2049046045aa1"
FILES = {
    "config.json": "ce02c0c0d02f285d2ff34c80b0867ccb5c4a3b250a275e6d1d2884f5499a6e46",
    "model.bin": "a07b5103b41acba9c3ae718f75c2f6031d9f497075bcd903c1015ceaede2e8de",
    "shared_vocabulary.json": "78c1ea4f71b7d582051c7250032d2d959e60c5d42078f5d540951153ad836774",
    "source.spm": "f538d23d4b30641cd97c608d2a83890d503aa1286a5560f19ef949404a786e94",
    "target.spm": "d05781fde84b8793191528a7a176e1b17f96265388f602379ee6ae3139f59141",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(target: Path) -> None:
    """Fill `target` with the model; files that are already there and match are left alone."""
    target.mkdir(parents=True, exist_ok=True)
    for name, expected in FILES.items():
        path = target / name
        if path.is_file() and _sha256(path) == expected:
            continue
        url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{name}"
        with httpx.stream("GET", url, follow_redirects=True, timeout=300) as response:
            response.raise_for_status()
            with path.open("wb") as handle:
                for chunk in response.iter_bytes(1 << 20):
                    handle.write(chunk)
        if _sha256(path) != expected:
            path.unlink()
            raise SystemExit(f"{name}: checksum mismatch, refusing to use it")


if __name__ == "__main__":
    fetch(Path(sys.argv[1]))
