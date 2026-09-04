import calendar
import json
import os
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")

# Use absolute paths based on the script's directory to ensure Render finds them
BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "tracker_data.json"
USERS_FILE = BASE_DIR / "users.json"
UPLOADS_DIR = BASE_DIR / "uploads"
ALLOWED_UPLOAD_EXTENSIONS = {
    "pdf", "doc", "docx", "txt", "rtf", "ppt", "pptx", "xls", "xlsx",
    "mp4", "webm", "mov", "avi", "mkv", "mp3", "wav", "m4a", "png", "jpg", "jpeg"
}
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024


def default_data():
    return {
        "tasks": [],
        "goals": [],
        "library": [],
        "study_sessions": [],
        "profile": {
            "subjects": [],
            "daily_target": 60,
            "photo": "",
        },
        "progress": {
            "study_hours": 0,
            "weekly_goal": 10,
            "completion_rate": 0,
            "current_streak": 0,
            "best_streak": 0,
        },
    }


def normalize_user_record(record):
    if isinstance(record, dict):
        return {"password": record.get("password", ""), "role": record.get("role", "Student")}
    return {"password": record or "", "role": "Student"}


def allowed_upload(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_UPLOAD_EXTENSIONS


def get_user_role(username):
    return normalize_user_record(load_users().get(username)).get("role", "Student")


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
    user_data = data[username]
    user_data.setdefault("study_sessions", [])
    user_data.setdefault("tasks", [])
    user_data.setdefault("goals", [])
    user_data.setdefault("library", [])
    user_data.setdefault("profile", {"subjects": [], "daily_target": 60, "photo": ""})
    user_data.setdefault("progress", default_data()["progress"].copy())
    return user_data


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

    planner_items = []
    for task in sorted(tasks, key=lambda item: item.get("due_date") or ""):
        due_date = task.get("due_date")
        if not due_date or task.get("completed"):
            continue
        try:
            due_value = date.fromisoformat(due_date)
        except ValueError:
            continue
        if today <= due_value <= today + timedelta(days=6):
            planner_items.append({
                "day": due_value.strftime("%a"),
                "title": task.get("title", "Untitled task"),
                "priority": task.get("priority", "medium"),
            })

    month_days = []
    first_day = date(today.year, today.month, 1)
    for _ in range((first_day.weekday() + 1) % 7):
        month_days.append({"empty": True, "day": ""})

    for day_number in range(1, calendar.monthrange(today.year, today.month)[1] + 1):
        current_day = date(today.year, today.month, day_number)
        month_days.append({
            "empty": False,
            "day": day_number,
            "date": current_day.isoformat(),
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
        "planner_items": planner_items,
        "month_label": today.strftime("%B %Y"),
        "month_days": month_days,
        "insights": insights,
        "tasks_left": max(0, total_count - completed_count),
        "total_count": total_count,
        "completed_count": completed_count,
        "pending_count": max(0, total_count - completed_count),
        "library_count": len(user_data.get("library", [])),
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
        week_before = due_value == today + timedelta(days=7)
        overdue = due_value < today

        if (reminder in {"same-day", "custom"} and same_day) or (
            reminder == "1-day" and (same_day or next_day)
        ) or (reminder == "1-week" and (same_day or week_before)) or (
            reminder == "overdue" and overdue
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
        is_overdue = due_value < today
        if is_due_today or is_due_tomorrow_for_one_day_reminder or is_overdue:
            due_list.append(task)

    summary_text = "Today is clear. Keep your momentum going." if not due_list else (
        "Today’s focus: " + ", ".join(task["title"] for task in due_list[:3])
    )

    return {
        "has_due_tasks": bool(due_list),
        "summary_text": summary_text,
        "due_count": len(due_list),
        "overdue_count": sum(1 for task in due_list if task.get("due_date", "") < today.isoformat()),
    }


def get_goal_milestone_alerts(user_data):
    if not user_data:
        return []

    alerts = []
    for goal in user_data.get("goals", []):
        target = max(1, int(goal.get("target", 1)))
        progress = min(target, max(0, int(goal.get("progress", 0))))
        percentage = int((progress / target) * 100)
        notified = {int(value) for value in goal.get("milestones_notified", []) if str(value).isdigit()}
        reached = [milestone for milestone in (25, 50, 75, 100) if percentage >= milestone and milestone not in notified]
        if reached:
            milestone = max(reached)
            alerts.append({
                "type": "goal",
                "title": f"{goal.get('title', 'Goal')} reached {milestone}%",
                "milestone": milestone,
            })
            notified.update(reached)
        elif percentage and percentage > max(notified, default=0) and percentage not in notified:
            alerts.append({
                "type": "goal",
                "title": f"{goal.get('title', 'Goal')} reached {percentage}%",
                "milestone": percentage,
            })
            notified.add(percentage)
        goal["milestones_notified"] = sorted(notified)
    return alerts


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "Student")

        users = load_users()
        account = normalize_user_record(users.get(username))
        if username in users and account["password"] == password and account["role"] == role:
            session["username"] = username
            return redirect(url_for("index"))
        return render_template("login.html", error="Invalid username or password", mode="login")

    return render_template("login.html", error=None, mode="login")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "Student")

        if not username or not password:
            return render_template("login.html", error="Username and password are required", mode="signup")

        users = load_users()
        if username in users:
            return render_template("login.html", error="Username already exists", mode="signup")

        users[username] = {"password": password, "role": role}
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


@app.route("/settings", methods=["POST"])
def settings():
    redirect_to_login = require_login()
    if redirect_to_login:
        return redirect_to_login

    user_data = get_current_user_data()
    profile = user_data.setdefault("profile", {"subjects": [], "daily_target": 60, "photo": ""})
    subjects = [item.strip() for item in request.form.get("subjects", "").split(",") if item.strip()]
    try:
        daily_target = min(1440, max(1, int(request.form.get("daily_target", 60))))
    except (TypeError, ValueError):
        daily_target = 60
    profile["subjects"] = subjects
    profile["daily_target"] = daily_target

    photo = request.files.get("profile_photo")
    if photo and photo.filename and allowed_upload(photo.filename):
        safe_name = secure_filename(photo.filename)
        user_folder = UPLOADS_DIR / secure_filename(get_current_username())
        user_folder.mkdir(parents=True, exist_ok=True)
        photo.save(user_folder / safe_name)
        profile["photo"] = url_for("uploaded_file", username=get_current_username(), filename=safe_name)

    persist_current_user_data(user_data)
    return redirect(url_for("index"))


@app.route("/", methods=["GET", "POST"])
def index():
    redirect_to_login = require_login()
    if redirect_to_login:
        return redirect_to_login

    user_data = get_current_user_data()
    if user_data is None:
        return redirect(url_for("login"))

    reminder_alerts = get_reminder_alerts(user_data)
    goal_alerts = get_goal_milestone_alerts(user_data)
    if goal_alerts:
        persist_current_user_data(user_data)
    daily_summary = get_daily_summary(user_data)

    if request.method == "POST":
        tab = request.form.get("tab", "tasks")

        if tab == "tasks":
            task_name = request.form.get("task")
            priority = request.form.get("priority", "medium")
            due_date = request.form.get("task_due_date", "")
            reminder = request.form.get("task_reminder", "none")
            category = request.form.get("category", "General").strip() or "General"
            if task_name:
                user_data["tasks"].append({
                    "title": task_name,
                    "completed": False,
                    "priority": priority,
                    "due_date": due_date,
                    "reminder": reminder,
                    "category": category,
                })

        elif tab == "goals":
            goal_name = request.form.get("goal")
            goal_target = request.form.get("target", 1)
            try:
                target_value = int(goal_target)
            except (TypeError, ValueError):
                target_value = 1

            if goal_name:
                user_data["goals"].append({
                    "title": goal_name,
                    "progress": 0,
                    "target": max(1, target_value),
                    "milestones_notified": [],
                    "deadline": request.form.get("goal_deadline", ""),
                })

        elif tab == "library":
            library_name = request.form.get("library_title")
            library_type = request.form.get("library_type", "Notes")
            uploaded_file = request.files.get("library_file")
            if uploaded_file and uploaded_file.filename:
                if not allowed_upload(uploaded_file.filename):
                    return render_template("index.html", error="This file type is not supported.",
                                           tasks=user_data["tasks"], goals=user_data["goals"],
                                           library=user_data["library"], progress=user_data["progress"],
                                           completed_count=sum(1 for task in user_data["tasks"] if task.get("completed")),
                                           total_count=len(user_data["tasks"]), username=get_current_username(),
                                           role=get_user_role(get_current_username()), reminder_alerts=reminder_alerts,
                                           user_data=user_data,
                                           goal_alerts=goal_alerts, daily_summary=daily_summary,
                                           dashboard=build_dashboard_data(user_data))
                safe_name = secure_filename(uploaded_file.filename)
                user_folder = UPLOADS_DIR / secure_filename(get_current_username())
                user_folder.mkdir(parents=True, exist_ok=True)
                uploaded_file.save(user_folder / safe_name)
                user_data["library"].append({
                    "title": library_name or safe_name,
                    "type": library_type,
                    "filename": safe_name,
                    "url": url_for("uploaded_file", username=get_current_username(), filename=safe_name),
                })
            elif library_name:
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
        today=date.today().isoformat(),
        username=get_current_username(),
        role=get_user_role(get_current_username()),
        user_data=user_data,
        reminder_alerts=reminder_alerts,
        goal_alerts=goal_alerts,
        daily_summary=daily_summary,
        dashboard=dashboard,
    )


@app.route("/edit-task/<int:index>", methods=["POST"])
def edit_task(index):
    redirect_to_login = require_login()
    if redirect_to_login:
        return redirect_to_login

    user_data = get_current_user_data()
    if 0 <= index < len(user_data["tasks"]):
        task = user_data["tasks"][index]
        task["title"] = request.form.get("task", task.get("title", "Untitled task")).strip() or task.get("title", "Untitled task")
        task["due_date"] = request.form.get("task_due_date", "")
        task["priority"] = request.form.get("priority", "medium")
        task["category"] = request.form.get("category", "General").strip() or "General"
        task["reminder"] = request.form.get("task_reminder", "none")
        persist_current_user_data(user_data)
    return redirect(url_for("index"))


@app.route("/api/notifications")
def notifications():
    if not get_current_username():
        return jsonify({"notifications": []}), 401

    user_data = get_current_user_data()
    goal_alerts = get_goal_milestone_alerts(user_data)
    if goal_alerts:
        persist_current_user_data(user_data)

    notifications = [
        {
            "title": "Task reminder",
            "body": alert["title"],
            "tag": f"task-{alert['title']}-{alert['due_date']}",
        }
        for alert in get_reminder_alerts(user_data)
    ]
    notifications.extend(
        {"title": "Goal milestone", "body": alert["title"], "tag": f"goal-{alert['title']}"}
        for alert in goal_alerts
    )
    summary = get_daily_summary(user_data)
    if summary["has_due_tasks"]:
        notifications.append({
            "title": "VoltStudy daily summary",
            "body": summary["summary_text"],
            "tag": f"summary-{date.today().isoformat()}",
        })
    return jsonify({"notifications": notifications})


@app.route("/api/focus-session", methods=["POST"])
def focus_session():
    if not get_current_username():
        return jsonify({"error": "Login required"}), 401

    payload = request.get_json(silent=True) or {}
    try:
        minutes = int(payload.get("minutes", 0))
    except (TypeError, ValueError):
        minutes = 0
    if minutes < 1 or minutes > 240:
        return jsonify({"error": "Minutes must be between 1 and 240"}), 400

    user_data = get_current_user_data()
    user_data["study_sessions"].append({"minutes": minutes, "date": date.today().isoformat()})
    user_data["progress"]["study_hours"] = round(
        sum(session_item.get("minutes", 0) for session_item in user_data["study_sessions"]) / 60,
        2,
    )
    persist_current_user_data(user_data)
    return jsonify({"minutes": minutes, "study_hours": user_data["progress"]["study_hours"]})


@app.route("/uploads/<username>/<filename>")
def uploaded_file(username, filename):
    if username != get_current_username():
        return redirect(url_for("login"))
    return send_from_directory(UPLOADS_DIR / secure_filename(username), secure_filename(filename))


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
