from studio.execution_model.program import ExecutorAction, ExecutorProgram


def test_executor_action_to_dict_omits_none_fields():
    action = ExecutorAction(
        action="mkdir",
        path="app",
    )

    assert action.to_dict() == {
        "action": "mkdir",
        "path": "app",
    }


def test_executor_program_roundtrip_from_dicts():
    raw = [
        {
            "action": "write_file",
            "path": "app/main.py",
            "content": "print(1)",
            "extra": "ignored",
        },
        {
            "action": "run",
            "command": "pytest",
        },
    ]

    program = ExecutorProgram.from_dicts(raw)

    assert program.actions[0].action == "write_file"
    assert program.actions[0].metadata == {"extra": "ignored"}
    assert program.to_dicts() == [
        {
            "action": "write_file",
            "path": "app/main.py",
            "content": "print(1)",
            "extra": "ignored",
        },
        {
            "action": "run",
            "command": "pytest",
        },
    ]
