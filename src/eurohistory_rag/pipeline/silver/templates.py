from mwparserfromhell.nodes import Template
from mwparserfromhell.wikicode import Wikicode

KEEP: dict[str, tuple[int, ...]] = {
    "lang": (2,),  # {{lang|de|Reichstag}} -> Reichstag
    "convert": (1, 2),  # {{convert|50|km}}     -> 50 km
    "flag": (1,),  # {{flag|France}}       -> France
    "flagcountry": (1,),
    "nowrap": (1,),
}


def _flatten(template: Template) -> str | None:
    """The prose a kept template stands for, or None if it is not kept.

    None and "" mean different things here: None is "not on the list, leave it
    for strip_code", "" is "on the list but its parameters were empty".
    """
    positions = KEEP.get(str(template.name).strip().lower())
    if positions is None:
        return None
    return " ".join(
        str(template.get(i).value).strip() for i in positions if template.has(i)
    )


def rescue_templates(code: Wikicode) -> None:
    """Replace allow-listed templates in place with the text they render as.

    Mutates `code` and returns nothing; everything left behind is deleted later
    by strip_code(). That split is deliberate — this function only ever adds
    text back, so a mistake in KEEP can lose a word but can never leak citation
    parameters into the prose.
    """
    # Innermost first. filter_templates() yields an outer template before the
    # ones nested inside it, and replacing the outer one re-parses its text --
    # which resurrects an inner {{lang}} as a fresh node that this loop has
    # already passed, so it never gets rescued and strip_code eats it.
    for template in reversed(code.filter_templates()):
        text = _flatten(template)
        if text is not None:
            code.replace(template, text)
