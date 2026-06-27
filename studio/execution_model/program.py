from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass
class ExecutorAction:
    action: str
    path: str | None = None
    content: str | None = None
    command: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self):
        data = {
            "action": self.action,
        }

        if self.path is not None:
            data["path"] = self.path

        if self.content is not None:
            data["content"] = self.content

        if self.command is not None:
            data["command"] = self.command

        data.update(self.metadata)
        return data

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("Executor action must be an object")

        known_fields = {
            "action",
            "path",
            "content",
            "command",
        }

        return cls(
            action=data.get("action"),
            path=data.get("path"),
            content=data.get("content"),
            command=data.get("command"),
            metadata={key: value for key, value in data.items() if key not in known_fields},
        )


@dataclass
class ExecutorProgram:
    actions: list[ExecutorAction]

    @classmethod
    def from_dicts(cls, actions):
        if isinstance(actions, cls):
            return actions

        if not isinstance(actions, Iterable) or isinstance(actions, (str, bytes)):
            raise ValueError("Executor program must be a list of actions")

        return cls(actions=[ExecutorAction.from_dict(item) for item in actions])

    def to_dicts(self):
        return [action.to_dict() for action in self.actions]

    def __iter__(self):
        return iter(self.actions)

    def __len__(self):
        return len(self.actions)
