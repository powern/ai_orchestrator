import json
import re


def strip_markdown(text: str) -> str:
    text = text.strip()

    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if m:
        text = m.group(1)

    return text.strip()


def replace_triple_quotes(text: str) -> str:
    pattern = re.compile(r'"""(.*?)"""', re.DOTALL)

    def repl(match):
        return json.dumps(match.group(1))

    return pattern.sub(repl, text)


def repair(text: str) -> str:
    text = strip_markdown(text)
    text = replace_triple_quotes(text)
    return text
