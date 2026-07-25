from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from instance.models import db, Employee, Task
from utils.helpers import login_required
from utils.csrf import validate_csrf_token

tasks_bp = Blueprint('tasks', __name__)


@tasks_bp.route('/tasks', endpoint='tasks')
@login_required()
def tasks():
    tasks_list = Task.query.order_by(Task.date.desc()).all()
    return render_template('tasks.html', tasks=tasks_list)

@tasks_bp.route('/tasks/delete/<int:id>', methods=['POST'], endpoint='task_delete')
@login_required()
def task_delete(id):
    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
        return redirect(request.url)
    task = Task.query.get_or_404(id)
    db.session.delete(task)
    db.session.commit()
    flash('تم حذف المهمة بنجاح', 'success')
    return redirect(url_for('tasks.tasks'))

# ==========================================================================================
# AJAX Helper
# ==========================================================================================

@tasks_bp.route('/get_employees_by_department/<int:department_id>', endpoint='get_employees_by_department')
@login_required(api=True)
def get_employees_by_department(department_id):
    if department_id == 0:
        employees = Employee.query.all()
    else:
        employees = Employee.query.filter_by(department_id=department_id).all()

    employees_list = [{'id': emp.id, 'name': emp.name} for emp in employees]
    return jsonify(employees_list)
