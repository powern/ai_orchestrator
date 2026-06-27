from studio.config.settings import DEFAULT_MODELS
from studio.core.agent import BaseAgent


class PlannerAgent(BaseAgent):
    name = "planner"

    def __init__(self, model=None):
        self.model = model or DEFAULT_MODELS["planner"]

