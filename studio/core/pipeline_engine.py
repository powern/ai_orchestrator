from studio.core.pipeline import get_pipeline_stages


class PipelineEngine:

    def __init__(self):
        self.stages = get_pipeline_stages()

    def list_stages(self):
        return list(self.stages)
