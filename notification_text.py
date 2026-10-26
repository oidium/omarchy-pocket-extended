"""Plain-text compatibility for KDE Connect's conversation-only formatting.

Structural tags are removed before entity decoding so literal user markup survives.
No renderer, URI handling, resources or actions are involved.
"""
import html
import re

_STRUCTURE = re.compile(r'<br\s*/?>|</?b>', re.IGNORECASE)


def plain_conversation_text(text, is_conversation=False):
    if not is_conversation or not isinstance(text, str):
        return text
    structural = _STRUCTURE.sub(lambda m: '\n' if m.group().lower().startswith('<br') else '', text)
    return html.unescape(structural)
