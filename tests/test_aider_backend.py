from studio.code_backend.aider_backend import AiderBackend


def test_aider_backend_builds_command():
    backend = AiderBackend()

    command = backend.build_command(
        repo_path="/tmp/repo",
        task="Fix tests",
    )

    assert command[0] == "aider"
    assert "--yes" in command
    assert "--message" in command
    assert "Fix tests" in command
    assert "/tmp/repo" in command


def test_aider_backend_has_name():
    assert AiderBackend().name == "aider"
