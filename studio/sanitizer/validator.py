from studio.coder.pipeline import CoderPipeline
from studio.sanitizer.json_cleaner import clean_json_text


class JsonValidator:
    """
    Thin wrapper around the existing validation pipeline.

    In the future this class will completely replace direct
    usage of CoderPipeline inside the sanitizer.
    """

    def validate(self, json_text):
        return CoderPipeline().process(
            clean_json_text(json_text),
            max_attempts=1,
            retry_fn=None,
        )
