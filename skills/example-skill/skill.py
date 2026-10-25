"""
Example skill. Copy this folder, rename it, and edit skill.json + skill.py to
create your own. Every skill.py must define register(registry), which adds
one or more tools using the same registry.register(...) API used by the
built-in tools in core/tools/.
"""


def get_word_count(text: str) -> str:
    """Count words and characters in a piece of text."""
    words = len(text.split())
    chars = len(text)
    return f"'{text[:40]}{'...' if len(text) > 40 else ''}' has {words} words and {chars} characters."


def register(registry) -> None:
    registry.register(
        name="get_word_count",
        description="Count the number of words and characters in a piece of text.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to analyze."},
            },
            "required": ["text"],
        },
        func=get_word_count,
    )
