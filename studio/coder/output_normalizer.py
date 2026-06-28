import json
import re

KNOWN_TRIPLE_QUOTED_FIELDS = ("content", "command")


def normalize_output_text(text: str) -> str:
    value = strip_markdown_fences(text)
    value = replace_known_triple_quoted_values(value)
    return value.strip()


def strip_markdown_fences(text: str) -> str:
    value = text.strip()

    if not value.startswith("```"):
        return value

    lines = value.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]

    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]

    return "\n".join(lines).strip()


def replace_known_triple_quoted_values(text: str) -> str:
    field_pattern = "|".join(re.escape(field) for field in KNOWN_TRIPLE_QUOTED_FIELDS)
    pattern = re.compile(
        rf'("(?P<field>{field_pattern})"\s*:\s*)(?P<quote>"""|\'\'\')(?P<value>.*?)(?P=quote)',
        re.DOTALL,
    )

    def repl(match):
        return match.group(1) + json.dumps(match.group("value"))

    return pattern.sub(repl, text)
