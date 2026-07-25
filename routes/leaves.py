from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime, date, timedelta
from instance.models import db, Employee, Department, Attendance, Leave, Task
from utils.helpers import log_action, login_required
from utils.csrf import validate_csrf_token

leaves_bp = Blueprint('leaves', __name__)


@leaves_bp.route('/leaves', endpoint='leaves')
@login_required()
def leaves():
    leaves_list = Leave.query.order_by(Leave.created_at.desc()).all()
    tasks_list = Task.query.order_by(Task.date.desc()).all()

    # Build leave balance data for each employee (for use in the template)
    employees = Employee.query.filter_by(status='active').all()
    leave_balances = {}
    for emp in employees:
        leave_balances[emp.id] = {
            'annual_leave_balance': emp.annual_leave_balance if hasattr(emp, 'annual_leave_balance') and emp.annual_leave_balance is not None else 0,
            'sick_leave_balance': emp.sick_leave_balance if hasattr(emp, 'sick_leave_balance') and emp.sick_leave_balance is not None else 0,
            'employee_name': emp.name,
        }

    return render_template('leaves.html', leaves=leaves_list, tasks=tasks_list, leave_balances=leave_balances)

@leaves_bp.route('/leaves/add', methods=['GET', 'POST'], endpoint='leave_add')
@login_required()
def leave_add():
    employees = Employee.query.filter_by(status='active').all()

    if request.method == 'POST':
        if not validate_csrf_token(request.form.get('csrf_token')):
            flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
            return redirect(request.url)
        category = request.form.get('request_category')

        if category == 'leave':
            leave_type = request.form.get('leave_type')
            start_date_str = request.form.get('start_date')
            end_date_str = request.form.get('end_date')

            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except:
                flash('خطأ في التاريخ', 'danger')
                return redirect(url_for('leaves.leave_add'))

            start_time_val = None
            end_time_val = None
            if leave_type == 'hourly':
                start_time_str = request.form.get('start_time')
                end_time_str = request.form.get('end_time')
                if start_time_str and end_time_str:
                    start_time_val = datetime.strptime(start_time_str, '%H:%M').time()
                    end_time_val = datetime.strptime(end_time_str, '%H:%M').time()

            # تحويل employee_id من string إلى int
            emp_id = request.form.get('employee_id')
            try:
                emp_id = int(emp_id)
            except (ValueError, TypeError):
                flash('خطأ في اختيار الموظف', 'danger')
                return redirect(url_for('leaves.leave_add'))

            # --- Leave balance check before adding ---
            employee = Employee.query.get(emp_id)
            if employee and leave_type in ('paid', 'medical'):
                num_days = (end_date - start_date).days + 1
                if leave_type == 'paid':
                    current_balance = employee.annual_leave_balance if hasattr(employee, 'annual_leave_balance') and employee.annual_leave_balance is not None else 0
                    if num_days > current_balance:
                        flash(f'رصيد الإجازات السنوية غير كافٍ. المتاح: {current_balance} يوم، المطلوب: {num_days} يوم', 'danger')
                        return redirect(url_for('leaves.leave_add'))
                elif leave_type == 'medical':
                    current_balance = employee.sick_leave_balance if hasattr(employee, 'sick_leave_balance') and employee.sick_leave_balance is not None else 0
                    if num_days > current_balance:
                        flash(f'رصيد الإجازات المرضية غير كافٍ. المتاح: {current_balance} يوم، المطلوب: {num_days} يوم', 'danger')
                        return redirect(url_for('leaves.leave_add'))
            # --- End leave balance check ---

            leave = Leave(
                employee_id=emp_id,
                leave_type=leave_type,
                start_date=start_date,
                end_date=end_date,
                start_time=start_time_val,
                end_time=end_time_val,
                reason=request.form.get('reason'),
                status='pending'
            )
            db.session.add(leave)
            db.session.commit()
            flash('تم إضافة طلب الإجازة بنجاح', 'success')

        elif category == 'absence':
            # تسجيل غياب مباشر (مبرر أو غير مبرر)
            emp_id = request.form.get('employee_id')
            try:
                emp_id = int(emp_id)
            except (ValueError, TypeError):
                flash('خطأ في اختيار الموظف', 'danger')
                return redirect(url_for('leaves.leave_add'))

            absence_date_str = request.form.get('absence_date')
            absence_type = request.form.get('absence_type')  # justified, unjustified

            try:
                absence_date = datetime.strptime(absence_date_str, '%Y-%m-%d').date()
            except:
                flash('خطأ في التاريخ', 'danger')
                return redirect(url_for('leaves.leave_add'))

            # فحص إذا كان يوجد سجل حضور لنفس اليوم
            existing = Attendance.query.filter_by(
                employee_id=emp_id,
                date=absence_date
            ).first()

            if existing:
                existing.status = 'absent'
                existing.absence_type = absence_type
                existing.notes = f'غياب {"مبرر" if absence_type == "justified" else "غير مبرر"}'
            else:
                attendance = Attendance(
                    employee_id=emp_id,
                    date=absence_date,
                    status='absent',
                    absence_type=absence_type,
                    notes=f'غياب {"مبرر" if absence_type == "justified" else "غير مبرر"}'
                )
                db.session.add(attendance)

            db.session.commit()
            flash('تم تسجيل الغياب بنجاح', 'success')

        elif category == 'task':
            task_type = request.form.get('task_type')
            task_date_str = request.form.get('task_date')
            start_time_str = request.form.get('task_start_time')
            end_time_str = request.form.get('task_end_time')

            # تحويل employee_id من string إلى int
            emp_id = request.form.get('employee_id')
            try:
                emp_id = int(emp_id)
            except (ValueError, TypeError):
                flash('خطأ في اختيار الموظف', 'danger')
                return redirect(url_for('leaves.leave_add'))

            try:
                task_date = datetime.strptime(task_date_str, '%Y-%m-%d').date()
                start_time = datetime.strptime(start_time_str, '%H:%M').time()
                end_time = datetime.strptime(end_time_str, '%H:%M').time()
            except:
                flash('خطأ في البيانات المدخلة', 'danger')
                return redirect(url_for('leaves.leave_add'))

            dt_start = datetime.combine(task_date, start_time)
            dt_end = datetime.combine(task_date, end_time)
            diff = dt_end - dt_start
            hours = round(diff.total_seconds() / 3600, 2)

            task = Task(
                employee_id=emp_id,
                task_type=task_type,
                date=task_date,
                start_time=start_time,
                end_time=end_time,
                total_hours=hours,
                description=request.form.get('task_description')
            )
            db.session.add(task)
            db.session.commit()
            flash('تم تسجيل المهمة/العمل الإضافي بنجاح', 'success')

        return redirect(url_for('leaves.leaves'))

    default_tab = request.args.get('tab', 'leave')
    departments = Department.query.all()

    # Pass leave balance data for each employee to the add form
    leave_balances = {}
    for emp in employees:
        leave_balances[emp.id] = {
            'annual_leave_balance': emp.annual_leave_balance if hasattr(emp, 'annual_leave_balance') and emp.annual_leave_balance is not None else 0,
            'sick_leave_balance': emp.sick_leave_balance if hasattr(emp, 'sick_leave_balance') and emp.sick_leave_balance is not None else 0,
        }

    return render_template('leave_add.html', employees=employees, departments=departments, default_tab=default_tab, leave_balances=leave_balances)

@leaves_bp.route('/leaves/approve/<int:id>', endpoint='leave_approve')
@login_required()
def leave_approve(id):
    leave = Leave.query.get_or_404(id)
    leave.status = 'approved'

    # خريطة أنواع الإجازات بالعربي
    leave_type_names = {
        'paid': 'مأجورة', 'unpaid': 'بلا راتب',
        'medical': 'صحية', 'maternity': 'أمومة', 'hourly': 'ساعية'
    }
    type_label = leave_type_names.get(leave.leave_type, leave.leave_type)

    # --- Deduct leave balance for paid/medical leaves ---
    if leave.leave_type in ('paid', 'medical'):
        employee = Employee.query.get(leave.employee_id)
        if employee:
            num_days = (leave.end_date - leave.start_date).days + 1
            if leave.leave_type == 'paid':
                current_balance = employee.annual_leave_balance if hasattr(employee, 'annual_leave_balance') and employee.annual_leave_balance is not None else 0
                new_balance = max(0, current_balance - num_days)
                employee.annual_leave_balance = new_balance
            elif leave.leave_type == 'medical':
                current_balance = employee.sick_leave_balance if hasattr(employee, 'sick_leave_balance') and employee.sick_leave_balance is not None else 0
                new_balance = max(0, current_balance - num_days)
                employee.sick_leave_balance = new_balance
    # --- End deduct leave balance ---

    # الإجازة الساعية لا تنشئ سجل حضور يوم كامل
    # الموظف لازم يحضر عادي ويسجل خروج/رجوع إجازة بالكاميرا
    if leave.leave_type == 'hourly':
        db.session.commit()
        flash('تمت الموافقة على الإجازة الساعية - الموظف يجب أن يسجل خروج ورجوع الإجازة بالكاميرا', 'success')
        return redirect(url_for('leaves.leaves'))

    delta = leave.end_date - leave.start_date
    for i in range(delta.days + 1):
        current_date = leave.start_date + timedelta(days=i)
        existing = Attendance.query.filter_by(
            employee_id=leave.employee_id,
            date=current_date
        ).first()

        if not existing:
            attendance = Attendance(
                employee_id=leave.employee_id,
                date=current_date,
                status='leave',
                notes=f'إجازة {type_label}'
            )
            db.session.add(attendance)
        elif existing.status == 'absent':
            # تحويل سجل الغياب إلى إجازة (حالة الموافقة على إجازة بأثر رجعي)
            existing.status = 'leave'
            existing.absence_type = None
            existing.notes = f'إجازة {type_label} (كان مسجّل غياب)'
        # إذا كان existing.status شيء آخر (حاضر/متأخر/إجازة) ما نغيّره

    db.session.commit()
    flash('تمت الموافقة على الإجازة وتم خصم الأيام من الرصيد', 'success')
    return redirect(url_for('leaves.leaves'))

@leaves_bp.route('/leaves/reject/<int:id>', endpoint='leave_reject')
@login_required()
def leave_reject(id):
    leave = Leave.query.get_or_404(id)
    leave.status = 'rejected'
    db.session.commit()
    flash('تم رفض الإجازة', 'danger')
    return redirect(url_for('leaves.leaves'))

@leaves_bp.route('/leaves/delete/<int:id>', methods=['POST'], endpoint='leave_delete')
@login_required()
def leave_delete(id):
    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
        return redirect(request.url)
    leave = Leave.query.get_or_404(id)

    # --- Restore leave balance if the leave was approved and is paid/medical ---
    if leave.status == 'approved' and leave.leave_type in ('paid', 'medical'):
        employee = Employee.query.get(leave.employee_id)
        if employee:
            num_days = (leave.end_date - leave.start_date).days + 1
            if leave.leave_type == 'paid':
                current_balance = employee.annual_leave_balance if hasattr(employee, 'annual_leave_balance') and employee.annual_leave_balance is not None else 0
                employee.annual_leave_balance = current_balance + num_days
            elif leave.leave_type == 'medical':
                current_balance = employee.sick_leave_balance if hasattr(employee, 'sick_leave_balance') and employee.sick_leave_balance is not None else 0
                employee.sick_leave_balance = current_balance + num_days
    # --- End restore leave balance ---

    delta = leave.end_date - leave.start_date
    for i in range(delta.days + 1):
        current_date = leave.start_date + timedelta(days=i)
        Attendance.query.filter_by(
            employee_id=leave.employee_id,
            date=current_date,
            status='leave'
        ).delete()

    db.session.delete(leave)
    db.session.commit()
    flash('تم حذف الإجازة بنجاح وتم استعادة الأيام للرصيد', 'success')
    return redirect(url_for('leaves.leaves'))
