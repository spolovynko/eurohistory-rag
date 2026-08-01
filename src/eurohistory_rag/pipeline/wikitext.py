"""Wikilink knowledge shared by the Bronze and Silver stages.

Both stages ask the same two questions of a raw link target: is this a link to
an article, and what is the article called? Bronze asks to build the registry,
Silver asks to record what a document is about. One answer, one place.
"""

# Links into these namespaces are metadata or navigation, never article content.
NON_ARTICLE_NAMESPACES = frozenset(
    {
        "category",
        "file",
        "image",
        "media",
        "template",
        "module",
        "help",
        "portal",
        "wikipedia",
        "wp",
        "special",
        "talk",
        "user",
        "draft",
        "mediawiki",
        "book",
        "timedtext",
        "wikt",
        "commons",
        "s",
    }
)


def is_non_article(title: str) -> bool:
    """True for `Category:1957 in Europe` and friends, false for `Star Trek: TNG`.

    A fixed namespace list rather than "contains a colon", because plenty of
    article titles contain one. See D-024.
    """
    prefix, _, rest = title.partition(":")
    return bool(rest) and prefix.strip().lower() in NON_ARTICLE_NAMESPACES


def normalise_target(raw: str) -> str | None:
    """The article a wikilink points at, or None if it does not point at one.

    `[[world_war_I#Causes]]` and `[[World War I]]` are the same page, and
    MediaWiki capitalises the first letter of every title. Without those three
    normalisations the same article is counted as two.
    """
    title = raw.strip().lstrip(":").split("#", 1)[0].strip().replace("_", " ")
    if not title or is_non_article(title):
        return None
    return title[0].upper() + title[1:]
