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

        return data


@dataclass
class ExecutorProgram:
    actions: list[ExecutorAction]

    @classmethod
    def from_dicts(cls, actions):
        return cls(
            actions=[
                ExecutorAction(
                    action=item.get("action"),
                    path=item.get("path"),
                    content=item.get("content"),
                    command=item.get("command"),
                    metadata={
                        key: value
                        for key, value in item.items()
                        if key not in ("action", "path", "content", "command")
                    },
                )
                for item in actions
            ]
        )

    def to_dicts(self):
        return [
            action.to_dict()
            for action in self.actions
        ]
