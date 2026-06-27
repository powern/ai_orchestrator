from agents.architect import ArchitectAgent
from agents.coder import CoderAgent
from agents.planner import PlannerAgent
from agents.tester import AgentTester


def test_agents_have_expected_models():
    assert PlannerAgent().model == "qwen2.5:7b"
    assert ArchitectAgent().model == "qwen2.5:7b"
    assert CoderAgent().model == "qwen2.5-coder:3b"
    assert AgentTester().model == "qwen2.5-coder:1.5b"
