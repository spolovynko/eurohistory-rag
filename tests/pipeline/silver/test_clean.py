"""The cleaning pipeline: templates, footnotes, tables, wikilinks, whitespace."""

import mwparserfromhell

from eurohistory_rag.pipeline.silver.clean import (
    clean_wikitext,
    drop_non_article_links,
    drop_non_prose,
    link_targets,
    rescue_templates,
)


def parsed(wikitext: str) -> mwparserfromhell.wikicode.Wikicode:
    return mwparserfromhell.parse(wikitext)


# --- templates -------------------------------------------------------------


def test_an_unlisted_template_is_deleted_entirely() -> None:
    """The rule is allow-list, so an unknown template loses its parameters too."""
    assert clean_wikitext("Signed.{{sfn|Smith|2010|p=4}} Then.").text == "Signed. Then."


def test_a_listed_template_leaves_its_text_behind() -> None:
    assert clean_wikitext("The {{lang|de|Reichstag}} met.").text == "The Reichstag met."


def test_a_listed_template_can_keep_several_positions() -> None:
    assert clean_wikitext("Within {{convert|50|km}}.").text == "Within 50 km."


def test_a_nested_listed_template_survives_its_listed_parent() -> None:
    """Innermost first: replacing the outer one re-parses and would eat the inner."""
    text = clean_wikitext("{{nowrap|{{lang|fr|Entente}} cordiale}} held.").text

    assert text == "Entente cordiale held."


def test_a_listed_template_inside_a_deleted_one_goes_with_it() -> None:
    assert clean_wikitext("A{{sfn|{{lang|de|Reich}}|p=1}} B.").text == "A B."


def test_a_wrapper_template_keeps_every_positional_parameter() -> None:
    """Dates and lists carry their content across all positions, not a fixed one."""
    assert clean_wikitext("{{ubl|France|Britain}}").text == "France Britain"


def test_a_date_template_is_kept() -> None:
    """The hole that lost the Treaty of Versailles its signing date."""
    assert clean_wikitext("{{start date and age|28 June 1919}}").text == "28 June 1919"


def test_a_named_parameter_is_not_treated_as_content() -> None:
    assert clean_wikitext("{{ubl|France|link=yes}}").text == "France"


def test_a_listed_template_with_no_parameters_becomes_nothing() -> None:
    assert clean_wikitext("Before {{lang|de}} after.").text == "Before  after."


def test_rescue_leaves_unlisted_templates_in_place_for_the_strip() -> None:
    """It only ever adds text back; deleting is strip_code's job."""
    code = parsed("{{sfn|Smith}}")
    rescue_templates(code)

    assert str(code) == "{{sfn|Smith}}"


# --- footnotes and tables --------------------------------------------------


def test_a_footnote_is_removed_with_its_contents() -> None:
    """strip_code keeps <ref> contents, which would land mid-sentence."""
    assert clean_wikitext("Text.<ref>Smith, p. 4.</ref> More.").text == "Text. More."


def test_a_table_is_removed_with_its_contents() -> None:
    wikitext = "Before.\n{| class=wikitable\n! Year\n|-\n| 1919\n|}\nAfter."

    assert clean_wikitext(wikitext).text == "Before.\n\nAfter."


def test_a_footnote_inside_a_table_does_not_break_removal() -> None:
    wikitext = "A\n{|\n| 1919<ref>note</ref>\n|}\nB"
    code = parsed(wikitext)
    drop_non_prose(code)

    assert "1919" not in str(code)


def test_an_inline_tag_keeps_the_text_it_wraps() -> None:
    assert clean_wikitext("An ''italic'' word.").text == "An italic word."


# --- wikilinks -------------------------------------------------------------


def test_a_piped_link_keeps_the_words_a_reader_sees() -> None:
    text = clean_wikitext("The [[Treaty of Versailles|treaty]] failed.").text

    assert text == "The treaty failed."


def test_a_plain_link_keeps_its_title() -> None:
    assert clean_wikitext("In [[Weimar Republic]].").text == "In Weimar Republic."


def test_a_file_link_is_deleted_with_its_caption() -> None:
    """Otherwise strip_code emits `thumb|250px|...` verbatim."""
    wikitext = "See [[File:V.jpg|thumb|250px|The signing]] above."

    assert clean_wikitext(wikitext).text == "See  above."


def test_a_category_link_is_deleted() -> None:
    assert clean_wikitext("Text. [[:Category:Wars]]").text == "Text."


def test_link_targets_are_sorted_and_deduplicated() -> None:
    code = parsed("[[Rome]] [[Berlin]] [[rome]] [[Berlin#History|Berlin]]")

    assert link_targets(code) == ["Berlin", "Rome"]


def test_link_targets_exclude_files_and_categories() -> None:
    code = parsed("[[File:X.jpg|c]] [[Category:Wars]] [[Berlin]]")

    assert link_targets(code) == ["Berlin"]


def test_targets_describe_the_text_that_survived() -> None:
    """A link inside a deleted file caption is not what the section is about."""
    code = parsed("[[File:X.jpg|thumb|At [[Versailles]]]] and [[Berlin]].")
    drop_non_article_links(code)

    assert link_targets(code) == ["Berlin"]


# --- whitespace and the whole pipeline -------------------------------------


def test_a_non_breaking_space_becomes_an_ordinary_one() -> None:
    """They look identical and tokenize differently."""
    cleaned = clean_wikitext("World War&nbsp;I ended.")

    assert " " not in cleaned.text
    assert cleaned.text == "World War I ended."


def test_runs_of_blank_lines_collapse_to_one() -> None:
    assert clean_wikitext("A\n\n\n\n\nB").text == "A\n\nB"


def test_leading_and_trailing_whitespace_is_removed() -> None:
    assert clean_wikitext("\n\n  Text.  \n\n").text == "Text."


def test_empty_wikitext_gives_an_empty_document() -> None:
    cleaned = clean_wikitext("")

    assert cleaned.text == ""
    assert cleaned.link_targets == ()


def test_link_targets_come_back_as_a_tuple() -> None:
    """Frozen dataclass, so the field is immutable like the rest of it."""
    assert clean_wikitext("[[Berlin]]").link_targets == ("Berlin",)


def test_every_rule_applies_in_one_pass() -> None:
    wikitext = (
        "The [[Treaty of Versailles|treaty]]<ref>Smith, p. 4.</ref> was signed "
        "on {{start date and age|28 June 1919}} near [[File:V.jpg|thumb|Paris]] "
        "the {{lang|fr|Palais}}.{{sfn|Jones|2011}}"
    )

    cleaned = clean_wikitext(wikitext)

    assert cleaned.text == ("The treaty was signed on 28 June 1919 near  the Palais.")
    assert cleaned.link_targets == ("Treaty of Versailles",)
