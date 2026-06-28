from studio.coder.output_normalizer import normalize_output_text


def repair(text: str) -> str:
    return normalize_output_text(text)
