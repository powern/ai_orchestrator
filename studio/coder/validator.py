REQUIRED = {
    "mkdir": {"path"},
    "write_file": {"path", "content"},
    "read_file": {"path"},
    "run": {"command"},
}


def validate(actions):
    for action in actions:

        if "action" not in action:
            raise ValueError("Missing action field")

        action_type = action["action"]

        if action_type not in REQUIRED:
            raise ValueError(f"Unsupported action: {action_type}")

        missing = REQUIRED[action_type] - set(action.keys())

        if missing:
            raise ValueError(f"{action_type} missing fields: {sorted(missing)}")

    return actions
