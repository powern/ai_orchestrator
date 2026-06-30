import json

import pytest

from studio.contracts.engineering_plan import (
    EngineeringPlanValidationError,
    parse_engineering_plan,
)
from studio.core.action_builder import EngineeringPlanActionBuilder


def test_engineering_plan_builder_converts_plan_to_executor_actions():
    plan = parse_engineering_plan(
        json.dumps(
            {
                "schema_version": 1,
                "project_summary": "Create calculator package.",
                "tests": {"command": "pytest -q"},
                "steps": [
                    {
                        "type": "create_file",
                        "path": "app/calculator.py",
                        "purpose": "Calculator functions",
                        "content_description": "add function",
                        "content": "def add(a, b):\n    return a + b\n",
                    },
                    {"type": "run_tests"},
                ],
            }
        )
    )

    actions = EngineeringPlanActionBuilder().build(plan)

    assert actions == [
        {"action": "mkdir", "path": "app"},
        {
            "action": "write_file",
            "path": "app/calculator.py",
            "content": "def add(a, b):\n    return a + b\n",
        },
        {"action": "run", "command": "pytest -q"},
    ]


def test_engineering_plan_rejects_executor_json_root():
    with pytest.raises(EngineeringPlanValidationError, match="root must be an object"):
        parse_engineering_plan('[{"action": "write_file", "path": "app/main.py"}]')


def test_engineering_plan_requires_file_content():
    with pytest.raises(EngineeringPlanValidationError, match="must include content"):
        parse_engineering_plan(
            json.dumps(
                {
                    "schema_version": 1,
                    "steps": [
                        {
                            "type": "create_file",
                            "path": "app/main.py",
                            "purpose": "Entry point",
                            "content_description": "Missing content",
                        }
                    ],
                }
            )
        )


def test_action_builder_output_is_deterministic():
    payload = json.dumps(
        {
            "schema_version": 1,
            "steps": [
                {
                    "type": "create_file",
                    "path": "app/domain/model.py",
                    "purpose": "Domain model",
                    "content_description": "Model file",
                    "content": "VALUE = 1\n",
                }
            ],
        }
    )
    plan = parse_engineering_plan(payload)
    builder = EngineeringPlanActionBuilder()

    assert builder.build(plan) == builder.build(plan)
