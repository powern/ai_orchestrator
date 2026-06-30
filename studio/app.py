from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from studio.config.settings import FLASK_HOST, FLASK_PORT
from studio.contracts.handoff import load_handoff_history
from studio.core.project_state import ProjectStateBuilder
from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.events.publisher import publish_run_event
from studio.services.engineering_service import get_latest_engineering_assessment
from studio.services.event_service import list_events, list_latest_events
from studio.services.project_service import (
    create_project,
    get_dashboard_metrics,
    get_project,
    get_project_summary,
    list_project_summaries,
)
from studio.services.run_service import (
    create_run_if_not_active,
    get_next_run,
    get_previous_run,
    get_run,
    list_runs_for_project,
)
from studio.services.runtime_service import get_project_runtime

app = Flask(__name__)
init_db()
migrate()

STAGE_OUTPUT_FIELDS = [
    "planner_output",
    "architect_output",
    "coder_raw_output",
    "coder_sanitizer_error",
    "coder_output",
    "executor_output",
    "tester_output",
    "bug_report",
    "failure_analysis",
    "repair_plan",
    "fix_raw_output",
    "fix_sanitizer_error",
    "fix_output",
    "tester_output_before_fix",
    "tester_output_after_fix",
    "runtime_readiness",
    "result",
]


def row_to_dict(row):
    return dict(row) if row is not None else None


@app.route("/")
def index():
    projects = list_project_summaries()
    metrics = get_dashboard_metrics()
    return render_template("index.html", projects=projects, metrics=metrics)


@app.route("/projects/new", methods=["GET", "POST"])
def new_project():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()

        if not name or not description:
            return render_template(
                "new_project.html",
                error="Name and description are required.",
                name=name,
                description=description,
            )

        project_id = create_project(name, description)
        return redirect(url_for("project_detail", project_id=project_id))

    return render_template("new_project.html")


@app.route("/projects/<int:project_id>")
def project_detail(project_id):
    project = get_project(project_id)
    if project is None:
        abort(404)

    runs = list_runs_for_project(project_id)
    summary = get_project_summary(project_id)
    runtime = get_project_runtime(project_id)
    latest_events = list_latest_events(runs[0]["id"], limit=1) if runs else []
    latest_event = latest_events[0] if latest_events else None
    return render_template(
        "project_detail.html",
        project=project,
        summary=summary,
        runtime=runtime,
        latest_event=latest_event,
        runs=runs,
    )


@app.route("/projects/<int:project_id>/run", methods=["POST"])
def run_project(project_id):
    project = get_project(project_id)
    if project is None:
        abort(404)

    run_id, created = create_run_if_not_active(project_id)

    if not created:
        publish_run_event(
            run_id,
            project_id,
            event_type="run_already_active",
            stage="queued",
            message="An active run already exists for this project.",
        )
        return redirect(url_for("run_detail", run_id=run_id))

    publish_run_event(
        run_id,
        project_id,
        event_type="run_created",
        stage="queued",
        message="Run was created and added to queue.",
    )

    return redirect(url_for("run_detail", run_id=run_id))


@app.route("/runs/<int:run_id>")
def run_detail(run_id):
    run = get_run(run_id)
    if run is None:
        abort(404)

    project = get_project(run["project_id"])
    runtime = get_project_runtime(run["project_id"])
    previous_run = get_previous_run(run_id)
    next_run = get_next_run(run_id)
    events = list_events(run_id)
    engineering_assessment = get_latest_engineering_assessment(run_id)
    agent_handoffs = load_handoff_history(run_id)
    project_state = _project_state_for_run(run, agent_handoffs)
    return render_template(
        "run_detail.html",
        run=run,
        project=project,
        runtime=runtime,
        previous_run=previous_run,
        next_run=next_run,
        events=events,
        engineering_assessment=engineering_assessment,
        agent_handoffs=agent_handoffs,
        project_state=project_state,
    )


@app.get("/api/projects")
def api_projects():
    return jsonify(
        {
            "projects": list_project_summaries(),
            "metrics": get_dashboard_metrics(),
        }
    )


@app.get("/api/projects/<int:project_id>")
def api_project(project_id):
    project = get_project_summary(project_id)
    if project is None:
        abort(404)

    runs = [dict(row) for row in list_runs_for_project(project_id)]
    runtime = row_to_dict(get_project_runtime(project_id))

    return jsonify(
        {
            "project": project,
            "runtime": runtime,
            "runs": runs,
        }
    )


@app.get("/api/runs/<int:run_id>")
def api_run(run_id):
    run = get_run(run_id)
    if run is None:
        abort(404)

    project = get_project(run["project_id"])
    runtime = get_project_runtime(run["project_id"])
    engineering_assessment = get_latest_engineering_assessment(run_id)
    project_graph = engineering_assessment.get("project_graph") if engineering_assessment else None
    agent_handoffs = load_handoff_history(run_id)
    project_state = _project_state_for_run(run, agent_handoffs)
    return jsonify(
        {
            "run": row_to_dict(run),
            "project": row_to_dict(project),
            "runtime": row_to_dict(runtime),
            "events": [dict(row) for row in list_events(run_id)],
            "stage_outputs": {field: run[field] for field in STAGE_OUTPUT_FIELDS},
            "engineering_assessment": engineering_assessment,
            "project_graph": project_graph,
            "agent_handoffs": agent_handoffs,
            "project_state": project_state,
            "project_state_summary": project_state.get("summary", {}),
        }
    )


@app.get("/api/runtime")
def api_runtime():
    return jsonify(
        {
            "metrics": get_dashboard_metrics(),
            "projects": list_project_summaries(),
        }
    )


@app.get("/api/events/<int:run_id>")
def api_events(run_id):
    return jsonify({"events": [dict(row) for row in list_events(run_id)]})


def _project_state_for_run(run, handoff_history):
    if run is None:
        return {}
    project = row_to_dict(get_project(run["project_id"])) or {}
    payload = ProjectStateBuilder().build(
        run_id=run["id"],
        project_id=run["project_id"],
        workspace_path=project.get("workspace_path", ""),
        executor_actions=run["coder_output"],
        stage_outputs={field: run[field] for field in STAGE_OUTPUT_FIELDS if run[field]},
        handoff_history=handoff_history,
        request_text=project.get("description", ""),
    ).to_dict()
    for section_name in ("actual_files", "planned_files", "merged_files"):
        for item in payload.get(section_name, {}).get("files", []):
            item["content_preview"] = ""
    return payload


if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT)
