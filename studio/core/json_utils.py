from studio.coder.pipeline import CoderPipeline
from studio.coder.repair import repair


def strip_markdown_code_fence(text):
    return repair(text)


def normalize_coder_json_result(text):
    return CoderPipeline().process(text)


def normalize_coder_json(text):
    return normalize_coder_json_result(text).actions
