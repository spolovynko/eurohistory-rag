"""Article-level questions: is this content, what kind of thing, filed where."""

from eurohistory_rag.pipeline.silver.article import (
    extract_categories,
    extract_infobox,
    is_non_content,
)

# --- is_non_content --------------------------------------------------------


def test_an_ordinary_article_is_content() -> None:
    assert is_non_content("Treaty of Versailles", "Prose about the treaty.") is False


def test_a_list_article_is_not_content() -> None:
    """Its body is links to other articles, so a chunk from it holds no claim."""
    assert is_non_content("List of Cold War spy films", "* [[A]]\n* [[B]]") is True


def test_an_outline_article_is_not_content() -> None:
    assert is_non_content("Outline of the Cold War", "Prose.") is True


def test_the_prefix_test_is_case_insensitive() -> None:
    assert is_non_content("LIST OF treaties", "Prose.") is True


def test_a_title_merely_containing_list_is_content() -> None:
    """Prefix, not substring: the Schindler article is about a real subject."""
    assert is_non_content("Schindler's List", "Prose about the film.") is False


def test_a_disambiguation_title_is_not_content() -> None:
    assert is_non_content("Versailles (disambiguation)", "Prose.") is True


def test_a_disambiguation_template_is_not_content() -> None:
    """Not every disambiguation page says so in its title."""
    assert is_non_content("Verdun", "May refer to:\n{{disambiguation}}") is True


def test_a_redirect_is_not_content() -> None:
    assert is_non_content("Great War", "#REDIRECT [[World War I]]") is True


def test_a_stub_is_content() -> None:
    """Short about a real subject is not the same as being a menu."""
    wikitext = "Central European History is a journal.{{Europe-hist-stub}}"

    assert is_non_content("Central European History", wikitext) is False


# --- extract_infobox -------------------------------------------------------


def test_an_article_without_an_infobox_returns_none() -> None:
    assert extract_infobox("Just prose.") is None


def test_the_type_is_the_template_name_without_the_prefix() -> None:
    infobox = extract_infobox("{{Infobox treaty\n| name = Versailles\n}}")

    assert infobox is not None
    assert infobox.type == "treaty"


def test_field_values_are_cleaned_like_prose() -> None:
    """Values are wikitext too, so they go through the same rules."""
    infobox = extract_infobox(
        "{{Infobox treaty\n"
        "| date_signed = {{start date and age|28 June 1919}}{{sfn|S|2010}}\n"
        "| location_signed = [[Palace of Versailles|Versailles]]\n"
        "}}"
    )

    assert infobox is not None
    assert infobox.fields["date_signed"] == "28 June 1919"
    assert infobox.fields["location_signed"] == "Versailles"


def test_presentational_fields_are_dropped() -> None:
    """`image` and `caption` are the commonest fields and are facts about nothing."""
    infobox = extract_infobox(
        "{{Infobox treaty\n| image = V.jpg\n| caption = The signing\n| name = V\n}}"
    )

    assert infobox is not None
    assert set(infobox.fields) == {"name"}


def test_a_field_that_cleans_to_nothing_is_dropped() -> None:
    infobox = extract_infobox(
        "{{Infobox treaty\n| name = V\n| parties = {{flagicon|FR}}\n}}"
    )

    assert infobox is not None
    assert "parties" not in infobox.fields


def test_only_the_first_infobox_is_read() -> None:
    """A country with a box per era: the first is the one at the top of the page."""
    infobox = extract_infobox(
        "{{Infobox country\n| name = A\n}}\n"
        "Prose.\n"
        "{{Infobox former country\n| name = B\n}}"
    )

    assert infobox is not None
    assert infobox.type == "country"


def test_an_html_comment_in_the_template_name_is_not_part_of_the_type() -> None:
    """Six articles write `{{Infobox settlement<!-- see template:... -->`."""
    infobox = extract_infobox(
        "{{Infobox settlement<!-- see template:infobox settlement -->\n| name = A\n}}"
    )

    assert infobox is not None
    assert infobox.type == "settlement"


def test_a_box_with_only_presentational_fields_still_reports_its_type() -> None:
    infobox = extract_infobox("{{Infobox treaty\n| image = V.jpg\n}}")

    assert infobox is not None
    assert infobox.type == "treaty"
    assert infobox.fields == {}


# --- extract_categories ----------------------------------------------------


def test_categories_are_returned_sorted_and_deduplicated() -> None:
    wikitext = "[[Category:Wars]] [[Category:Treaties]] [[Category:Wars]]"

    assert extract_categories(wikitext) == ("Treaties", "Wars")


def test_underscores_in_a_category_become_spaces() -> None:
    assert extract_categories("[[Category:World_War_I]]") == ("World War I",)


def test_a_leading_colon_is_ignored() -> None:
    assert extract_categories("[[:Category:Wars]]") == ("Wars",)


def test_a_sort_key_is_not_part_of_the_name() -> None:
    """`[[Category:Wars|Versailles]]` files the page under Wars, not Versailles."""
    assert extract_categories("[[Category:Wars|Versailles]]") == ("Wars",)


def test_ordinary_links_are_not_categories() -> None:
    assert extract_categories("[[Berlin]] and [[File:X.jpg]]") == ()


def test_an_article_with_no_categories_returns_an_empty_tuple() -> None:
    assert extract_categories("Just prose.") == ()
