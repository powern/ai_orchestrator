from studio.config.settings import DEFAULT_MODELS
from studio.core.agent import BaseAgent


class AgentTester(BaseAgent):
    name = "tester"

    def __init__(self, model=None):
        self.model = model or DEFAULT_MODELS["tester"]
