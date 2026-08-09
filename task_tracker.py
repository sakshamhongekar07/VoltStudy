import calendar
import json
import os
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")

# Use absolute paths based on the script's directory to ensure Render finds them
BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "tracker_data.json"
USERS_FILE = BASE_DIR / "users.json"


def default_data():
    return {
        "tasks": [],
        "goals": [],
        "library": [],
        "progress": {
            "study_hours": 0,
            "weekly_goal": 10,
            "completion_rate": 0,
            "current_streak": 0,
            "best_streak": 0,
        },
    }


def load_users():
    if not USERS_FILE.exists():
        save_users({})
    try:
        with USERS_FILE.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        save_users({})
        return {}


def save_users(users):
    try:
        with USERS_FILE.open("w", encoding="utf-8") as fh:
            json.dump(users, fh, indent=2)
    except OSError:
        pass


def load_data():
    if not DATA_FILE.exists():
        save_data({})
        return {}

    try:
        with DATA_FILE.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        save_data({})
        return {}


def save_data(data):
    try:
        with DATA_FILE.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass


def get_current_username():
    return session.get("username")


def get_current_user_data():
    username = get_current_username()
    if not username:
        return None

    data = load_data()
    if username not in data:
        data[username] = default_data()
        save_data(data)
    return data[username]


def persist_current_user_data(user_data):
    username = get_current_username()
    if not username or user_data is None:
        return

    data = load_data()
    data[username] = user_data
    save_data(data)


def require_login():
    if not get_current_username():
        return redirect(url_for("login"))
    return None


def build_dashboard_data(user_data):
    tasks = user_data.get("tasks", [])
    goals = user_data.get("goals", [])
    total_count = len(tasks)
    completed_count = sum(1 for task in tasks if task.get("completed"))
    completion_rate = int((completed_count / total_count) * 100) if total_count else 0

    goal_progress = 0
    if goals:
        target_total = sum(max(1, goal.get("target", 1)) for goal in goals)
        current_total = sum(goal.get("progress", 0) for goal in goals)
        goal_progress = int((current_total / target_total) * 100) if target_total else 0

    today = date.today()
    weekly_activity = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        value = sum(1 for task in tasks if task.get("due_date") == day.isoformat())
        weekly_activity.append({"day": day.strftime("%a")[:3], "value": min(100, value * 25)})

    month_days = []
    first_day = date(today.year, today.month, 1)
    for _ in range(first_day.weekday()):
        month_days.append({"empty": True, "day": ""})

    for day_number in range(1, calendar.monthrange(today.year, today.month)[1] + 1):
        current_day = date(today.year, today.month, day_number)
        month_days.append({
            "empty": False,
            "day": day_number,
            "is_today": current_day == today,
            "is_active": any(task.get("due_date") == current_day.isoformat() for task in tasks),
        })

    insights = [
        {"label": "Smart plan", "value": "On track" if completion_rate >= 60 else "Needs focus"},
        {"label": "Goal pace", "value": "Strong" if goal_progress >= 60 else "Steady"},
        {"label": "Best slot", "value": "Evening" if completion_rate >= 40 else "Morning"},
    ]

    progress_hours = user_data.get("progress", {}).get("study_hours", 0)
    if not progress_hours and total_count:
        progress_hours = completed_count + max(0, total_count - completed_count) // 2

    return {
        "completion_rate": completion_rate,
        "goal_progress": goal_progress,
        "study_hours": progress_hours,
        "weekly_activity": weekly_activity,
        "month_days": month_days,
        "insights": insights,
        "tasks_left": max(0, total_count - completed_count),
        "total_count": total_count,
        "completed_count": completed_count,
    }


def normalize_task(task):
    if not isinstance(task, dict):
        return {}

    due_date = task.get("due_date") or ""
    reminder = task.get("reminder") or "none"
    is_completed = bool(task.get("completed", False))

    return {
        "title": task.get("title", "Untitled task"),
        "completed": is_completed,
        "priority": task.get("priority", "medium"),
        "due_date": due_date,
        "reminder": reminder,
    }


def get_reminder_alerts(user_data):
    if not user_data:
        return []

    today = date.today()
    alerts = []
    for task in user_data.get("tasks", []):
        normalized = normalize_task(task)
        if normalized.get("completed"):
            continue

        due_date = normalized.get("due_date")
        reminder = normalized.get("reminder", "none")
        if not due_date:
            continue

        try:
            due_value = date.fromisoformat(due_date)
        except ValueError:
            continue

        same_day = due_value == today
        next_day = due_value == today + timedelta(days=1)

        if (reminder in {"same-day", "1-day", "1-week", "custom"} and same_day) or (
            reminder == "1-day" and next_day
        ):
            alerts.append({
                "title": normalized["title"],
                "due_date": due_date,
                "priority": normalized["priority"],
                "reminder": reminder,
            })

    return alerts


def get_daily_summary(user_data):
    if not user_data:
        return {
            "has_due_tasks": False,
            "summary_text": "No tasks planned for today.",
            "due_count": 0,
        }

    today = date.today()
    tasks = user_data.get("tasks", [])
    pending = [normalize_task(task) for task in tasks if not task.get("completed", False)]
    due_list = []
    for task in pending:
        due_date = task.get("due_date")
        if not due_date:
            continue
        try:
            due_value = date.fromisoformat(due_date)
        except ValueError:
            continue

        is_due_today = due_value == today
        is_due_tomorrow_for_one_day_reminder = task.get("reminder") == "1-day" and due_value == today + timedelta(days=1)
        if is_due_today or is_due_tomorrow_for_one_day_reminder:
            due_list.append(task)

    summary_text = "Today is clear. Keep your momentum going." if not due_list else (
        "Today’s focus: " + ", ".join(task["title"] for task in due_list[:3])
    )

    return {
        "has_due_tasks": bool(due_list),
        "summary_text": summary_text,
        "due_count": len(due_list),
    }


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        users = load_users()
        if username in users and users[username] == password:
            session["username"] = username
            return redirect(url_for("index"))
        return render_template("login.html", error="Invalid username or password", mode="login")

    return render_template("login.html", error=None, mode="login")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            return render_template("login.html", error="Username and password are required", mode="signup")

        users = load_users()
        if username in users:
            return render_template("login.html", error="Username already exists", mode="signup")

        users[username] = password
        save_users(users)

        data = load_data()
        data[username] = default_data()
        save_data(data)

        session["username"] = username
        return redirect(url_for("login"))

    return render_template("login.html", error=None, mode="signup")


@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("login"))


@app.route("/", methods=["GET", "POST"])
def index():
    redirect_to_login = require_login()
    if redirect_to_login:
        return redirect_to_login

    user_data = get_current_user_data()
    if user_data is None:
        return redirect(url_for("login"))

    reminder_alerts = get_reminder_alerts(user_data)
    daily_summary = get_daily_summary(user_data)

    if request.method == "POST":
        tab = request.form.get("tab", "tasks")

        if tab == "tasks":
            task_name = request.form.get("task")
            priority = request.form.get("priority", "medium")
            due_date = request.form.get("task_due_date", "")
            reminder = request.form.get("task_reminder", "none")
            if task_name:
                user_data["tasks"].append({
                    "title": task_name,
                    "completed": False,
                    "priority": priority,
                    "due_date": due_date,
                    "reminder": reminder,
                })

        elif tab == "goals":
            goal_name = request.form.get("goal")
            goal_target = request.form.get("target", 1)
            try:
                target_value = int(goal_target)
            except (TypeError, ValueError):
                target_value = 1

            if goal_name:
                user_data["goals"].append({"title": goal_name, "progress": 0, "target": max(1, target_value)})

        elif tab == "library":
            library_name = request.form.get("library_title")
            library_type = request.form.get("library_type", "Notes")
            if library_name:
                user_data["library"].append({"title": library_name, "type": library_type})

        persist_current_user_data(user_data)
        return redirect(url_for("index"))

    completed_count = sum(1 for t in user_data["tasks"] if t["completed"])
    total_count = len(user_data["tasks"])
    user_data["progress"]["completion_rate"] = int((completed_count / total_count) * 100) if total_count else 0

    dashboard = build_dashboard_data(user_data)

    return render_template(
        "index.html",
        tasks=user_data["tasks"],
        goals=user_data["goals"],
        library=user_data["library"],
        progress=user_data["progress"],
        completed_count=completed_count,
        total_count=total_count,
        username=get_current_username(),
        reminder_alerts=reminder_alerts,
        daily_summary=daily_summary,
        dashboard=dashboard,
    )


@app.route("/complete/<int:index>")
def complete_task(index):
    redirect_to_login = require_login()
    if redirect_to_login:
        return redirect_to_login

    user_data = get_current_user_data()
    if user_data is None:
        return redirect(url_for("login"))

    if 0 <= index < len(user_data["tasks"]):
        user_data["tasks"][index]["completed"] = not user_data["tasks"][index]["completed"]
        persist_current_user_data(user_data)
    return redirect(url_for("index"))


@app.route("/delete/<int:index>")
def delete_task(index):
    redirect_to_login = require_login()
    if redirect_to_login:
        return redirect_to_login

    user_data = get_current_user_data()
    if user_data is None:
        return redirect(url_for("login"))

    if 0 <= index < len(user_data["tasks"]):
        user_data["tasks"].pop(index)
        persist_current_user_data(user_data)
    return redirect(url_for("index"))


@app.route("/toggle-goal/<int:index>")
def toggle_goal(index):
    redirect_to_login = require_login()
    if redirect_to_login:
        return redirect_to_login

    user_data = get_current_user_data()
    if user_data is None:
        return redirect(url_for("login"))

    if 0 <= index < len(user_data["goals"]):
        goal = user_data["goals"][index]
        if goal["progress"] >= goal["target"]:
            goal["progress"] = 0
        else:
            goal["progress"] += 1
        persist_current_user_data(user_data)
    return redirect(url_for("index"))


@app.route("/delete-goal/<int:index>")
def delete_goal(index):
    redirect_to_login = require_login()
    if redirect_to_login:
        return redirect_to_login

    user_data = get_current_user_data()
    if user_data is None:
        return redirect(url_for("login"))

    if 0 <= index < len(user_data["goals"]):
        user_data["goals"].pop(index)
        persist_current_user_data(user_data)
    return redirect(url_for("index"))


@app.route("/delete-library/<int:index>")
def delete_library(index):
    redirect_to_login = require_login()
    if redirect_to_login:
        return redirect_to_login

    user_data = get_current_user_data()
    if user_data is None:
        return redirect(url_for("login"))

    if 0 <= index < len(user_data["library"]):
        user_data["library"].pop(index)
        persist_current_user_data(user_data)
    return redirect(url_for("index"))


@app.route("/clear-completed")
def clear_completed():
    redirect_to_login = require_login()
    if redirect_to_login:
        return redirect_to_login

    user_data = get_current_user_data()
    if user_data is None:
        return redirect(url_for("login"))

    user_data["tasks"] = [task for task in user_data["tasks"] if not task["completed"]]
    persist_current_user_data(user_data)
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=False)
