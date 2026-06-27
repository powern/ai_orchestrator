def clean_json_text(text: str) -> str:
    value = text.strip()

    if value.startswith("```"):
        lines = value.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        value = "\n".join(lines).strip()

    return value
