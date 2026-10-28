import pytest

from shelfsense.textutil import (
    detect_language,
    is_affirmative,
    is_negative,
    normalize_tokens,
    parse_budget,
    sanitize_user_text,
    scrub_pii,
)


@pytest.mark.parametrize(
    "text,budget",
    [
        ("wireless earbuds under 1000", 1000.0),
        ("pasta below ₹300", 300.0),
        ("charger within Rs. 1,500", 1500.0),
        ("earphones 500 se kam", 500.0),
        ("చక్కెర 100 లోపు", 100.0),
        ("just a plain query", None),
    ],
)
def test_parse_budget(text, budget):
    assert parse_budget(text)[0] == budget


def test_budget_phrase_removed_from_query():
    _, rest = parse_budget("wireless earbuds under 1000")
    assert "1000" not in rest and "earbuds" in rest


def test_vernacular_synonyms_map_to_canonical():
    assert normalize_tokens("mujhe chini chahiye") == ["sugar"]
    assert normalize_tokens("చక్కెర కావాలి") == ["sugar"]
    assert normalize_tokens("ragi cookies") == ["millet", "biscuit"]
    assert normalize_tokens("gluten-free pasta") == ["glutenfree", "pasta"]


@pytest.mark.parametrize(
    "text,lang",
    [
        ("I need sugar", "en"),
        ("मुझे चीनी चाहिए", "hi"),
        ("నాకు చక్కెర కావాలి", "te"),
        ("mujhe atta chahiye", "hi"),
        ("naku biyyam kavali", "te"),
    ],
)
def test_language_detection(text, lang):
    assert detect_language(text) == lang


def test_consent_intents():
    assert is_affirmative("yes please") and is_affirmative("haan") and is_affirmative("అవును")
    assert is_negative("no thanks") and is_negative("नहीं")
    assert not is_affirmative("no, not yes") and not is_affirmative(
        "I would like to buy a very large amount of rice"
    )


def test_pii_scrubbed():
    out = scrub_pii("call me on +91 98765 43210 or a.b@example.com")
    assert "9876" not in out and "example.com" not in out


def test_sanitize_strips_control_chars_and_caps_length():
    assert sanitize_user_text("hi\x00\x07 there") == "hi there"
    assert len(sanitize_user_text("x" * 5000)) == 400
