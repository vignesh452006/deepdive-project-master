from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash

from controller.config import Config
from controller.database import db
from datetime import datetime
from datetime import date
from controller.models import Admin, User, Role, UserRole, Staff, Student, Quiz, Question, Option,StudentResult
from sqlalchemy import or_
from gemini_service import QuizGenerator # Make sure the file name matches exactly
import json

import os

app = Flask(__name__,
            template_folder=os.path.join(os.getcwd(), "templates"),
            static_folder=os.path.join(os.getcwd(), "static"))
app.config.from_object(Config)
app.secret_key = "quiz-master-secret"

db.init_app(app)

# ---------------- INIT DB, SEED ROLES & ADMIN ----------------
with app.app_context():
    db.create_all()

    # Seed roles
    for r in ["staff", "student"]:
        if not Role.query.filter_by(name=r).first():
            db.session.add(Role(name=r))
    db.session.commit()

    # Hardcoded admin in admins table
    admin_email = "admin@gmail.com"
    admin_user = Admin.query.filter_by(email=admin_email).first()
    if not admin_user:
        admin_user = Admin(
            username="admin",
            email=admin_email,
            password=generate_password_hash("admin123")
        )
        db.session.add(admin_user)
        db.session.commit()
        print("✅ Admin created in admins table")

# ---------------- HOME ----------------
@app.route("/")
def home():
    admin = Admin.query.first()   # fetch admin from DB
    return render_template("home.html", admin=admin)

# ---------------- REGISTER (STAFF/STUDENT) ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        role_name = request.form.get("role")

        if role_name not in ["staff", "student"]:
            flash("Select Staff or Student role", "danger")
            return redirect(url_for("register"))

        if User.query.filter_by(email=email).first():
            flash("User already exists", "danger")
            return redirect(url_for("register"))

        user = User(
            username=username,
            email=email,
            password=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()

        role = Role.query.filter_by(name=role_name).first()
        db.session.add(UserRole(user_id=user.id, role_id=role.id))

        # create staff/student profile
        if role_name == "staff":
            db.session.add(Staff(user_id=user.id, full_name=username))
        else:
            db.session.add(Student(user_id=user.id, full_name=username))

        db.session.commit()

        flash("Registered successfully. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        # -------- ADMIN LOGIN --------
        admin = Admin.query.filter_by(email=email).first()
        if admin and check_password_hash(admin.password, password):
            session["user_id"] = admin.id
            session["username"] = admin.username
            session["role"] = "admin"
            return redirect(url_for("admin_dashboard"))

        # -------- USER LOGIN --------
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password, password):
            flash("Invalid credentials", "danger")
            return redirect(url_for("login"))

        ur = UserRole.query.filter_by(user_id=user.id).first()
        role = db.session.get(Role, ur.role_id)

        session["user_id"] = user.id
        session["username"] = user.username
        session["role"] = role.name

        if role.name == "staff":
            return redirect(url_for("staff_dashboard"))
        else:
            return redirect(url_for("student_dashboard"))

    return render_template("login.html")
@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    user = User.query.filter_by(email=email).first()
    if user and user.password == password:
        role = UserRole.query.filter_by(user_id=user.id).first()
        return {
            "status": "success",
            "user_id": user.id,
            "role": role.role.name
        }

    return {"status": "error", "message": "Invalid credentials"}, 401

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------- DASHBOARDS ----------------
from sqlalchemy import or_

# ---------------- ADMIN DASHBOARD ----------------
from datetime import date

@app.route("/admin")
@app.route("/admin/dashboard")
def admin_dashboard():
    # Ensure only admins can access
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    page = request.args.get("page", 1, type=int)

    # Query users with their role
    students = db.session.query(
        User, 
        Role.name.label("role")
    ).join(
        UserRole, User.id == UserRole.user_id
    ).join(
        Role, Role.id == UserRole.role_id
    ).paginate(page=page, per_page=5)

    # Query quizzes
    quizzes = Quiz.query.paginate(page=page, per_page=5)

    return render_template(
        "admin_dashboard.html",
        username=session.get("username"),
        students=students,
        quizzes=quizzes
    )


# ---------------- ADMIN SEARCH ----------------
@app.route("/admin_search")
def admin_search():
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 5

    students = User.query.join(UserRole).join(Role)\
        .filter(Role.name=="student",
                or_(User.username.ilike(f"%{q}%"),
                    User.email.ilike(f"%{q}%")))\
        .paginate(page=page, per_page=per_page)

    staff = User.query.join(UserRole).join(Role)\
        .filter(Role.name=="staff",
                or_(User.username.ilike(f"%{q}%"),
                    User.email.ilike(f"%{q}%")))\
        .paginate(page=page, per_page=per_page)

    quizzes = Quiz.query.filter(
        or_(Quiz.subject.ilike(f"%{q}%"),
            Quiz.chapter.ilike(f"%{q}%"))
    ).paginate(page=page, per_page=per_page)

    return render_template("admin_dashboard.html",
                           username=session.get("username"),
                           students=students,
                           staff=staff,
                           quizzes=quizzes)


# ---------------- EDIT USER ----------------
@app.route("/admin/edit_user/<int:user_id>", methods=["POST"])
def admin_edit_user(user_id):
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    user = User.query.get_or_404(user_id)
    user.username = request.form["username"]
    user.email = request.form["email"]
    db.session.commit()
    flash("User updated successfully", "success")
    return redirect(url_for("admin_dashboard"))


# ---------------- DELETE USER ----------------
@app.route("/admin/delete_user/<int:user_id>")
def admin_delete_user(user_id):
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    user = User.query.get_or_404(user_id)
    UserRole.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    flash("User deleted successfully", "success")
    return redirect(url_for("admin_dashboard"))


# ---------------- ADMIN SUMMARY ----------------
@app.route("/admin/summary")
def admin_summary():
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    total_students = UserRole.query.join(Role)\
        .filter(Role.name == "student").count()

    total_staff = UserRole.query.join(Role)\
        .filter(Role.name == "staff").count()

    total_quizzes = Quiz.query.count()

    return render_template(
        "admin_summary.html",
        total_students=total_students,
        total_staff=total_staff,
        total_quizzes=total_quizzes
    )






# ---------------- ADMIN SETTINGS ----------------
@app.route("/admin/settings")
def admin_settings():
    if session.get("role") != "admin":
        return redirect(url_for("login"))
    return render_template("admin_settings.html")


@app.route("/staff")
def staff_dashboard():
    if session.get("role") != "staff":
        return redirect(url_for("login"))
    return render_template("staff_dashboard.html",
                           username=session.get("username"))

@app.route("/view_quizzes")
def view_quizzes():
    if session.get("role") != "student":
        return redirect(url_for("login"))

    q = request.args.get("q", "").strip()

    if q:
        quizzes = Quiz.query.filter(
            (Quiz.subject.ilike(f"%{q}%")) |
            (Quiz.chapter.ilike(f"%{q}%"))
        ).all()
    else:
        quizzes = Quiz.query.all()

    return render_template("view_quizzes.html", quizzes=quizzes, query=q)

@app.route("/view_quiz/<int:quiz_id>")
def view_quiz(quiz_id):
    if session.get("role") != "student":
        return redirect(url_for("login"))

    quiz = Quiz.query.get_or_404(quiz_id)

    questions = Question.query.filter_by(quiz_id=quiz.id).all()

    related_quizzes = Quiz.query.filter(
        Quiz.subject == quiz.subject,
        Quiz.id != quiz.id
    ).all()

    return render_template(
        "view_quiz.html",
        quiz=quiz,
        questions=questions,
        related_quizzes=related_quizzes
    )



@app.route("/start_quiz/<int:quiz_id>", methods=["GET", "POST"])
def start_quiz(quiz_id):
    if session.get("role") != "student":
        return redirect(url_for("login"))

    quiz = Quiz.query.get_or_404(quiz_id)
    questions = Question.query.filter_by(quiz_id=quiz.id).all()

    if request.method == "POST":
        score = 0
        for q in questions:
            selected = request.form.get(str(q.id))
            if selected:
                opt = Option.query.get(int(selected))
                if opt and opt.is_correct:
                    score += 1

        result = StudentResult(
            student_id=session["user_id"],
            quiz_id=quiz.id,
            score=score,
            taken_at=datetime.utcnow()
        )
        db.session.add(result)
        db.session.commit()

        flash("Quiz submitted successfully!", "success")
        return redirect(url_for("view_results"))

    return render_template("start_quiz.html",
                           quiz=quiz,
                           questions=questions)

@app.route("/student")
def student_dashboard():
    if session.get("role") != "student":
        return redirect(url_for("login"))

    upcoming_quizzes = Quiz.query.all()  # no date filter

    return render_template(
        "student_dashboard.html",
        username=session.get("username"),
        upcoming_quizzes=upcoming_quizzes
    )


@app.route("/create_quiz", methods=["GET", "POST"])
def create_quiz():
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    if request.method == "POST":
        subject = request.form.get("subject")
        chapter = request.form.get("chapter")
        quiz_date = request.form.get("date")
        duration = request.form.get("duration")

        if not subject or not chapter or not quiz_date or not duration:
            flash("All fields are required.", "danger")
            return redirect(url_for("create_quiz"))

        quiz = Quiz(
            subject=subject,
            chapter=chapter,
            date=datetime.strptime(quiz_date, "%Y-%m-%d").date(),
            duration=int(duration)
        )
        db.session.add(quiz)
        db.session.flush()  # get quiz.id

        q_no = 1
        while f"question_{q_no}" in request.form:
            q_text = request.form.get(f"question_{q_no}")

            question = Question(text=q_text, quiz_id=quiz.id)
            db.session.add(question)
            db.session.flush()

            correct = request.form.get(f"q{q_no}_correct")

            for opt in ["a", "b", "c", "d"]:
                opt_text = request.form.get(f"q{q_no}_{opt}")
                option = Option(
                    text=opt_text,
                    is_correct=(correct == opt),
                    question_id=question.id
                )
                db.session.add(option)

            q_no += 1

        db.session.commit()
        flash("Quiz created successfully!", "success")
        return redirect(url_for("staff_dashboard"))

    return render_template("create_quiz.html")

@app.route("/manage_quizzes", methods=["GET", "POST"])
def manage_quizzes():
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    quizzes = Quiz.query.all()
    return render_template("manage_quizzes.html", quizzes=quizzes)


@app.route("/add_question/<int:quiz_id>", methods=["POST"])
def add_question(quiz_id):
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    q_text = request.form["question"]
    correct = request.form["correct"]

    question = Question(text=q_text, quiz_id=quiz_id)
    db.session.add(question)
    db.session.flush()  # get question.id

    for i in range(4):
        opt_text = request.form[f"opt{i}"]
        option = Option(
            text=opt_text,
            is_correct=(str(i) == correct),
            question_id=question.id
        )
        db.session.add(option)

    db.session.commit()
    flash("Question added!", "success")
    return redirect(url_for("manage_quizzes"))


@app.route("/update_question/<int:question_id>", methods=["POST"])
def update_question(question_id):
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    question = Question.query.get_or_404(question_id)
    question.text = request.form["question"]
    correct = request.form["correct"]

    for i, opt in enumerate(question.options):
        opt.text = request.form[f"opt{i}"]
        opt.is_correct = (str(i) == correct)

    db.session.commit()
    flash("Question updated!", "success")
    return redirect(url_for("manage_quizzes"))


@app.route("/delete_question/<int:question_id>", methods=["POST"])
def delete_question(question_id):
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    q = Question.query.get_or_404(question_id)
    db.session.delete(q)
    db.session.commit()
    flash("Question deleted!", "success")
    return redirect(url_for("manage_quizzes"))

@app.route("/attempt_quiz", methods=["GET", "POST"])
def attempt_quiz():
    if session.get("role") != "student":
        return redirect(url_for("login"))

    # Load all quizzes for dropdown
    quizzes = Quiz.query.all()
    quiz = None

    # ---------------- LOAD QUIZ (GET) ----------------
    quiz_id = request.args.get("quiz_id")
    if quiz_id:
        quiz = Quiz.query.get_or_404(int(quiz_id))

    # ---------------- SUBMIT QUIZ (POST) ----------------
    if request.method == "POST":
        quiz_id = int(request.form.get("quiz_id"))
        quiz = Quiz.query.get_or_404(quiz_id)

        score = 0
        total = len(quiz.questions)

        for q in quiz.questions:
            selected_opt_id = request.form.get(f"q{q.id}")
            if selected_opt_id:
                opt = Option.query.get(int(selected_opt_id))
                if opt and opt.is_correct:
                    score += 1

        # ✅ Save result
        result = StudentResult(
            student_id=session.get("user_id"),
            quiz_id=quiz.id,
            score=score
        )
        db.session.add(result)
        db.session.commit()

        flash(f"Quiz submitted! Your score: {score} / {total}", "success")
        return redirect(url_for("view_results"))

    # ---------------- RENDER PAGE ----------------
    return render_template(
        "attempt_quiz.html",
        quizzes=quizzes,
        quiz=quiz
    )


@app.route("/view_results")
def view_results():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    role = session.get("role")

    if role == "student":
        student_id = session.get("user_id")
        results = StudentResult.query.filter_by(student_id=student_id)\
                                     .order_by(StudentResult.taken_at.desc()).all()
    elif role == "staff":
        results = StudentResult.query.order_by(StudentResult.taken_at.desc()).all()
    else:
        return redirect(url_for("login"))

    return render_template("view_results.html",
                           results=results,
                           role=role)



# ---------- SETTINGS / MANAGE STUDENTS ----------
@app.route("/settings")
def settings():
    if session.get("role") != "staff":
        return redirect(url_for("login"))
    students = User.query.join(UserRole).join(Role)\
        .filter(Role.name == "student").all()
    return render_template("settings.html", students=students)

# ---------- UPDATE STUDENT ----------
@app.route("/update_student/<int:student_id>", methods=["POST"])
def update_student(student_id):
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    student = User.query.get_or_404(student_id)
    student.username = request.form["username"]
    student.email = request.form["email"]

    db.session.commit()
    flash("Student updated successfully", "success")
    return redirect(url_for("settings"))

# ---------- DELETE STUDENT ----------
@app.route("/delete_student/<int:student_id>")
def delete_student(student_id):
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    student = User.query.get_or_404(student_id)
    db.session.delete(student)
    db.session.commit()

    flash("Student deleted successfully", "success")
    return redirect(url_for("settings"))



@app.route("/staff_search_students", methods=["GET"])
def staff_search_students():
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    query = request.args.get("q", "").strip()

    students = []
    results = []

    if query:
        # 🔍 Search students by name or email
        students = User.query.join(UserRole).join(Role)\
            .filter(Role.name == "student")\
            .filter(
                or_(
                    User.username.ilike(f"%{query}%"),
                    User.email.ilike(f"%{query}%")
                )
            ).all()

        # 🔍 Search results by student name or quiz subject
        results = StudentResult.query\
            .join(User, StudentResult.student_id == User.id)\
            .join(Quiz, StudentResult.quiz_id == Quiz.id)\
            .filter(
                or_(
                    User.username.ilike(f"%{query}%"),
                    Quiz.subject.ilike(f"%{query}%")
                )
            ).all()

    return render_template(
        "manage_students.html",
        query=query,
        students=students,
        results=results
    )




@app.route("/summary")
def summary():
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    total_students = UserRole.query.join(Role)\
        .filter(Role.name == "student").count()

    attempted = StudentResult.query.distinct(StudentResult.student_id).count()
    not_attempted = max(total_students - attempted, 0)

    results = StudentResult.query\
        .order_by(StudentResult.taken_at.desc()).all()

    return render_template(
        "summary.html",
        total_students=total_students,
        attempted=attempted,
        not_attempted=not_attempted,
        results = results
    )
from sqlalchemy import func

@app.route("/student_summary")
def student_summary():
    if session.get("role") != "student":
        return redirect(url_for("login"))

    student_id = session.get("user_id")

    # Total quizzes available
    total_quizzes = Quiz.query.count()

    # Quizzes attempted by this student
    attempted = StudentResult.query.filter_by(student_id=student_id).count()

    not_attempted = total_quizzes - attempted if total_quizzes >= attempted else 0

    return render_template(
        "student_summary.html",
        attempted=attempted,
        not_attempted=not_attempted,
        username=session.get("username")
    )

@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user = User.query.get(session["user_id"])
    students = User.query.join(UserRole).join(Role)\
                .filter(Role.name == "student").all()
    quizzes = Quiz.query.all()

    return render_template("profile.html",
                           user=user,
                           role=session.get("role"),
                           students=students,
                           quizzes=quizzes)

@app.route("/edit_profile", methods=["POST"])
def edit_profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user = User.query.get(session["user_id"])
    user.username = request.form["username"]
    user.email = request.form["email"]

    db.session.commit()
    flash("Profile updated successfully", "success")
    return redirect(url_for("profile"))

from functools import wraps
from flask import session, redirect, url_for

def staff_or_admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") not in ["staff", "admin"]:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


@staff_or_admin_required
def edit_student(student_id):
    student = User.query.get_or_404(student_id)

    if request.method == "POST":
        student.username = request.form["username"]
        student.email = request.form["email"]
        db.session.commit()
        flash("Student updated successfully", "success")
        return redirect(url_for("profile"))

    return render_template("edit_student.html", student=student)
@app.route("/edit_quiz/<int:quiz_id>", methods=["GET", "POST"])
@staff_or_admin_required
def edit_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)

    if request.method == "POST":
        quiz.subject = request.form["subject"]
        quiz.chapter = request.form["chapter"]
        db.session.commit()
        flash("Quiz updated successfully", "success")
        return redirect(url_for("profile"))

    return render_template("edit_quiz.html", quiz=quiz)
@app.route("/delete_quiz/<int:quiz_id>")
@staff_or_admin_required
def delete_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)

    # delete dependent results first
    StudentResult.query.filter_by(quiz_id=quiz.id).delete()

    db.session.delete(quiz)
    db.session.commit()

    flash("Quiz deleted successfully", "success")
    return redirect(url_for("profile"))

@app.route("/manage_subjects", methods=["POST"])
@staff_or_admin_required
def manage_subjects():
    subject = request.form["subject"]
    chapter = request.form["chapter"]

    quiz = Quiz(subject=subject, chapter=chapter)
    db.session.add(quiz)
    db.session.commit()

    flash("Subject & chapter added successfully", "success")
    return redirect(url_for("profile"))


# ---------------- RUN ----------------

import json
import re
from flask import jsonify, request, session, redirect, url_for, flash
from gemini_service import QuizGenerator
# Import your database models here (e.g., from models import db, Quiz, Question)

@app.route("/ai_generate_quiz", methods=["POST"])
def ai_generate_quiz():
    if session.get("role") != "staff":
        return jsonify({"status": "error", "error": "Unauthorized"}), 403

    topic = request.form.get("topic")
    num_q = request.form.get("num_questions", 3)

    try:
        generator = QuizGenerator()
        raw_response = generator.generate_quiz(topic, int(num_q))

        # CLEANING: Removes markdown backticks so JSON parsing doesn't fail
        clean_json = re.sub(r'^```(?:json)?\s*|```\s*$', '', raw_response.strip(), flags=re.MULTILINE)
        
        # Ensure we only have the array part
        start = clean_json.find('[')
        end = clean_json.rfind(']') + 1
        if start != -1 and end != 0:
            clean_json = clean_json[start:end]

        quiz_data = json.loads(clean_json)
        return jsonify({"status": "success", "questions": quiz_data})

    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/create_quiz", methods=["POST"])
def save_quiz():
    """
    This handles the 'Save Full Quiz' button click.
    It reads all the questions (AI-generated or manual) and saves them to the DB.
    """
    try:
        subject = request.form.get("subject")
        chapter = request.form.get("chapter")
        # Add logic to save to your specific Database here
        # Example: 
        # new_quiz = Quiz(subject=subject, chapter=chapter, created_by=session['user_id'])
        # db.session.add(new_quiz)
        # db.session.commit()

        flash("Quiz saved successfully!", "success")
        return redirect(url_for('staff_dashboard'))
    except Exception as e:
        flash(f"Error saving quiz: {str(e)}", "danger")
        return redirect(url_for('create_quiz'))




