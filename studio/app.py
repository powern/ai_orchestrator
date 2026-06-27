from flask import Flask, render_template, request, redirect, url_for, abort

from studio.config.settings import FLASK_HOST, FLASK_PORT
from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.services.project_service import create_project, list_projects, get_project
from studio.services.run_service import create_run, list_runs_for_project, get_run
from studio.services.event_service import add_event, list_events


app = Flask(__name__)
init_db()
migrate()


@app.route("/")
def index():
    projects = list_projects()
    return render_template("index.html", projects=projects)


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
    return render_template("project_detail.html", project=project, runs=runs)


@app.route("/projects/<int:project_id>/run", methods=["POST"])
def run_project(project_id):
    project = get_project(project_id)
    if project is None:
        abort(404)

    run_id = create_run(project_id)
    add_event(
        run_id,
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

    events = list_events(run_id)
    return render_template("run_detail.html", run=run, events=events)


if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT)
