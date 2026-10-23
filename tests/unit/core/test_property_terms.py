"""Glossary helpers: ideas in a text, other-language expansion, canonical tokens."""

from app.core.property_terms import GROUPS, canonical_tokens, expand, fold, groups_in


def test_fold_removes_accents_and_case() -> None:
    assert fold("Beëindiging") == "beeindiging"


def test_dutch_and_english_words_of_one_idea_share_a_group() -> None:
    assert groups_in("What is the deposit?") == groups_in("Wat is de waarborgsom?") == ["deposit"]
    assert groups_in("opzegtermijn en huur") == ["notice", "rent"]


def test_multi_word_terms_are_found_as_phrases() -> None:
    assert "arrears" in groups_in("Er is een betaling te laat gedaan")  # "te laat" is the arrears phrase
    assert "notice_of_default" in groups_in("Ingebrekestelling ontvangen")


def test_expand_adds_the_other_language_and_not_what_is_already_there() -> None:
    got = expand("deposit")
    assert "waarborgsom" in got
    assert "deposit" not in got
    assert "deposit" in expand("waarborgsom")
    assert expand("hello world") == []


def test_expand_skips_phrases_because_it_feeds_single_word_search() -> None:
    assert all(" " not in w for w in expand("lease"))


def test_canonical_tokens_map_words_to_ideas_and_keep_the_rest() -> None:
    assert canonical_tokens("De waarborgsom is twee maanden") == [
        "deposit",
        "twee",
        "maanden",
    ]  # function words dropped
    assert canonical_tokens("deposit") == canonical_tokens("borg") == ["deposit"]


def test_groups_do_not_share_words() -> None:
    seen: dict[str, str] = {}
    for key, terms in GROUPS.items():
        for term in terms:
            for word in fold(term).split():
                if len(word) >= 3 and " " not in term:
                    assert seen.setdefault(word, key) == key, f"{word!r} is in {seen[word]} and {key}"
