ACTION_ALIASES = {
    "mkdir": "mkdir",
    "make_dir": "mkdir",
    "make_directory": "mkdir",
    "create_dir": "mkdir",
    "create_directory": "mkdir",

    "write_file": "write_file",
    "create_file": "write_file",
    "write": "write_file",
    "append_content": "write_file",
    "append_file": "write_file",

    "read_file": "read_file",
    "read": "read_file",

    "run": "run",
    "execute": "run",
    "shell": "run",
    "command": "run",
    "run_command": "run",
    "execute_command": "run",
    "shell_command": "run",
}


PATH_ALIASES = [
    "path",
    "file_path",
    "directory_path",
    "dir_path",
    "target",
]


COMMAND_ALIASES = [
    "command",
    "cmd",
    "shell_command",
]


def normalize_action_name(action_name):
    if action_name not in ACTION_ALIASES:
        return action_name

    return ACTION_ALIASES[action_name]


def normalize_path(action):
    if "path" in action:
        return action

    for key in PATH_ALIASES:
        if key in action:
            action["path"] = action.pop(key)
            return action

    return action


def normalize_command(action):
    if "command" in action:
        return action

    for key in COMMAND_ALIASES:
        if key in action:
            action["command"] = action.pop(key)
            return action

    return action



def normalize_shorthand_action(action):
    if "action" in action or "type" in action or "operation" in action:
        return action

    known = [
        "mkdir",
        "write_file",
        "read_file",
        "run",
    ]

    present = [key for key in known if key in action]

    if len(present) != 1:
        return action

    name = present[0]
    value = action[name]

    if isinstance(value, dict):
        normalized = dict(value)
        normalized["action"] = name
        return normalized

    if name == "run":
        return {
            "action": "run",
            "command": value,
        }

    return {
        "action": name,
        "path": value,
    }



def expand_batch_actions(actions):
    expanded = []

    for action in actions:
        if not isinstance(action, dict):
            expanded.append(action)
            continue

        if "mkdir" in action and isinstance(action["mkdir"], list):
            for path in action["mkdir"]:
                expanded.append({
                    "action": "mkdir",
                    "path": path,
                })
            continue

        if "write_file" in action and isinstance(action["write_file"], list):
            for item in action["write_file"]:
                expanded.append({
                    "action": "write_file",
                    **item,
                })
            continue

        if "run" in action and isinstance(action["run"], list):
            for command in action["run"]:
                expanded.append({
                    "action": "run",
                    "command": command,
                })
            continue

        expanded.append(action)

    return expanded



def normalize_write_file_content(action):
    if action.get("action") == "write_file":
        if "content" not in action and "command" in action:
            action["content"] = action.pop("command")

    return action



def expand_path_list_actions(actions):
    expanded = []

    for action in actions:
        if not isinstance(action, dict):
            expanded.append(action)
            continue

        path = action.get("path")

        if isinstance(path, list):
            for item in path:
                copy = dict(action)
                copy["path"] = item
                expanded.append(copy)
            continue

        expanded.append(action)

    return expanded


def normalize(actions):
    actions = expand_batch_actions(actions)
    actions = expand_path_list_actions(actions)
    normalized = []

    for action in actions:
        action = dict(action)
        action = normalize_shorthand_action(action)

        if "type" in action and "action" not in action:
            action["action"] = action.pop("type")

        if "operation" in action and "action" not in action:
            action["action"] = action.pop("operation")

        if "action" in action:
            action["action"] = normalize_action_name(action["action"])

        action = normalize_path(action)
        action = normalize_command(action)
        action = normalize_write_file_content(action)

        action.pop("id", None)

        normalized.append(action)

    return normalized
