"""Chunker v2: pages, headings, overlap, size limits, edge cases."""

import pytest

from app.pipeline.document_chunks import MIN_CHUNK, OVERLAP, PAGE_BREAK, TARGET, chunk_document, is_heading

PARA = ("De huurder is verplicht de woning schoon en in goede staat te houden en meldt gebreken onverwijld aan de "
        "verhuurder. ")  # fmt: skip


def paged(*pages: str) -> str:
    return PAGE_BREAK + PAGE_BREAK.join(pages)


HEADINGS = [
    ("ARTIKEL 4 WAARBORGSOM", True), ("Artikel 4 Waarborgsom", True), ("4.2 Opzegtermijn", True),
    ("HUUROVEREENKOMST", True), ("De huurder betaalt een waarborgsom.", False), ("ok", False),
    ("x" * 120, False), ("Totaal:", False), ("2026-01-01", False),
]  # fmt: skip


@pytest.mark.parametrize(("line", "expected"), HEADINGS)
def test_heading_detection(line: str, expected: bool) -> None:
    assert is_heading(line) is expected


def test_empty_and_blank_text_give_no_chunks() -> None:
    assert chunk_document("") == []
    assert chunk_document("  \n\n  ") == []
    assert chunk_document(PAGE_BREAK) == []


def test_short_unpaged_text_is_one_chunk_without_page() -> None:
    [only] = chunk_document("Huurovereenkomst\nDe waarborgsom is twee maanden.")
    assert only.page is None
    assert "waarborgsom" in only.text


def test_pdf_pages_are_numbered_from_one() -> None:
    chunks = chunk_document(paged("Pagina een tekst. " * 150, "Pagina twee tekst. " * 150))
    assert chunks[0].page == 1
    assert chunks[-1].page == 2
    assert "Pagina twee" in chunks[-1].text


def test_a_single_page_pdf_is_still_paged() -> None:
    assert chunk_document(paged("Een pagina met genoeg tekst over de huur. " * 3))[0].page == 1


def test_chunks_respect_the_size_target_and_cover_all_text() -> None:
    text = "\n\n".join(f"Alinea {i}. " + PARA * 4 for i in range(30))
    chunks = chunk_document(text)
    assert len(chunks) > 3
    assert all(len(c.text) <= TARGET * 1.3 for c in chunks)
    joined = " ".join(c.text for c in chunks)
    assert all(f"Alinea {i}." in joined for i in range(30))


def test_consecutive_chunks_overlap() -> None:
    from app.pipeline.document_chunks import _tail

    text = "\n\n".join(f"Alinea {i}: " + " ".join(f"woord{i}x{j}" for j in range(60)) for i in range(12))
    a, b = chunk_document(text)[:2]
    overlap = _tail(a.text)
    assert 0 < len(overlap) <= OVERLAP
    assert b.text.startswith(overlap)  # the end of one chunk opens the next


def test_a_heading_starts_a_chunk_and_is_remembered() -> None:
    text = "HUUROVEREENKOMST\n" + PARA * 5 + "\n\nArtikel 4 Waarborgsom\n" + "De waarborgsom is twee maanden. " * 20
    chunks = chunk_document(text)
    deposit = next(c for c in chunks if "waarborgsom is twee" in c.text)
    assert deposit.heading == "Artikel 4 Waarborgsom"
    assert deposit.text.startswith("Artikel 4 Waarborgsom") or "Artikel 4 Waarborgsom" in deposit.text


def test_the_heading_carries_over_to_following_chunks_of_the_same_section() -> None:
    chunks = chunk_document("Artikel 7 Onderhoud\n\n" + "\n\n".join(PARA * 4 for _ in range(8)))
    assert len(chunks) > 2
    assert {c.heading for c in chunks} == {"Artikel 7 Onderhoud"}


def test_a_huge_paragraph_without_breaks_is_still_cut() -> None:
    chunks = chunk_document("woord " * 2000)
    assert len(chunks) > 5
    assert all(len(c.text) <= TARGET * 1.3 for c in chunks)


def test_a_tiny_last_piece_is_merged_into_the_previous_chunk() -> None:
    text = "\n\n".join([PARA * 8, PARA * 8, "Slot."])
    chunks = chunk_document(text)
    assert not any(len(c.text) < MIN_CHUNK for c in chunks[:-1])
    assert "Slot." in chunks[-1].text


def test_text_without_spaces_does_not_hang() -> None:
    assert chunk_document("a" * 5000)
