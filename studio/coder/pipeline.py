import ast
import json

from studio.coder.normalizer import normalize
from studio.coder.repair import repair
from studio.coder.result import PipelineResult
from studio.coder.validator import validate


class CoderPipeline:

    def retry_with(self, retry_fn, original_output: str, error: Exception):
        return retry_fn(original_output, error)

    def process(self, llm_output: str, max_attempts: int = 1, retry_fn=None):
        last_error = None
        current_output = llm_output

        for attempt in range(1, max_attempts + 1):
            repaired = repair(current_output)

            try:
                try:
                    actions = json.loads(repaired)
                except json.JSONDecodeError:
                    actions = ast.literal_eval(repaired)

                if not isinstance(actions, list):
                    raise ValueError("Coder JSON root must be a list")

                actions = normalize(actions)
                actions = validate(actions)

                return PipelineResult(
                    actions=actions,
                    raw_output=llm_output,
                    repaired_output=repaired,
                    attempts=attempt,
                    retried=(attempt > 1),
                    validation_error=None,
                )

            except Exception as exc:
                last_error = exc

                if attempt >= max_attempts:
                    raise

                if retry_fn is None:
                    current_output = repaired
                else:
                    current_output = self.retry_with(
                        retry_fn,
                        current_output,
                        exc,
                    )

        raise last_error
