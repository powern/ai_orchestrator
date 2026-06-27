PIPELINE_STAGES = [
    "planner",
    "architect",
    "coder",
    "executor",
    "tester",
]


FINAL_STAGE = "completed"
FAILED_STAGE = "failed"


def get_pipeline_stages():
    return list(PIPELINE_STAGES)
