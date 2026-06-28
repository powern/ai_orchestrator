from studio.core.run_pipeline import RunPipeline


def test_pipeline_class_exists():
    pipeline = RunPipeline(lambda *_: "planner")
    assert pipeline is not None


def test_pipeline_runs_fix_when_static_review_fails(monkeypatch, tmp_path):
    from studio.core import run_pipeline
    from studio.core.run_pipeline import RunPipeline
    from studio.core.tester_result import StageTestResult

    calls = {
        "fix": 0,
        "executor": 0,
        "tester": 0,
    }

    project = {
        "workspace_path": str(tmp_path),
    }

    def fake_planner(run_id, project):
        return "planner"

    def fake_architect(run_id, planner_output):
        return "architect"

    def fake_coder(run_id, planner_output, architect_output):
        return """
        [
          {
            "action": "write_file",
            "path": "app/main.py",
            "content": "print('Hello, World!')"
          }
        ]
        """

    def fake_fix(run_id, workspace_path, coder_output, tester_result):
        calls["fix"] += 1
        return {
            "output": """
            [
              {
                "action": "write_file",
                "path": "app/main.py",
                "content": "def main():\\n    return 'fixed'\\n"
              }
            ]
            """,
            "results": [],
        }

    def fake_sanitize_fix_output(run_id, fix_output):
        return (
            [
                {
                    "action": "write_file",
                    "path": "app/main.py",
                    "content": "def main():\n    return 'fixed'\n",
                }
            ],
            """
            [
              {
                "action": "write_file",
                "path": "app/main.py",
                "content": "def main():\\n    return 'fixed'\\n"
              }
            ]
            """,
        )

    def fake_executor(run_id, workspace_path, coder_output):
        calls["executor"] += 1
        return []

    def fake_tester(run_id, workspace_path):
        calls["tester"] += 1
        return StageTestResult(
            success=True,
            returncode=0,
            stdout="ok",
            stderr="",
        )

    monkeypatch.setattr(run_pipeline, "run_architect_stage", fake_architect)
    monkeypatch.setattr(run_pipeline, "run_coder_placeholder", fake_coder)
    monkeypatch.setattr(
        run_pipeline,
        "_run_fix_stage_with_context",
        lambda run_id, workspace_path, coder_output, tester_result, context: fake_fix(
            run_id,
            workspace_path,
            coder_output,
            tester_result,
        ),
    )
    monkeypatch.setattr(run_pipeline, "sanitize_fix_output", fake_sanitize_fix_output)
    monkeypatch.setattr(run_pipeline, "run_executor_stage", fake_executor)
    monkeypatch.setattr(run_pipeline, "run_tester_stage", fake_tester)
    monkeypatch.setattr(
        run_pipeline,
        "run_runtime_readiness_stage",
        lambda *args, **kwargs: (True, None),
    )
    monkeypatch.setattr(run_pipeline, "update_run_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(run_pipeline, "add_event", lambda *args, **kwargs: None)

    RunPipeline(fake_planner).execute(1, project)

    assert calls["fix"] == 1
    assert calls["executor"] == 1
    assert calls["tester"] == 1
