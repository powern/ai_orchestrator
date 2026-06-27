import pytest

from studio.core.agent import BaseAgent


class EchoAgent(BaseAgent):
    name = "echo"

    def process(self, value):
        return value


def test_base_agent_run_calls_process():
    agent = EchoAgent()

    assert agent.run("hello") == "hello"
    assert agent.name == "echo"


def test_base_agent_process_must_be_implemented():
    agent = BaseAgent()

    with pytest.raises(NotImplementedError):
        agent.process()
