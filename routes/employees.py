from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import date, datetime, time, timedelta
import os
from sqlalchemy import func, or_
from instance.models import db, Employee, Department, Attendance, Leave, Task
from utils.helpers import log_action, login_required
from utils.face_utils import update_embedding_cache
from utils.csrf import validate_csrf_token

employees_bp = Blueprint('employees', __name__)


@employees_bp.route('/employees', endpoint='employees')
@login_required()
def employees():
    # بحث وترقيم صفحات
    search_query = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 15

    query = Employee.query
    if search_query:
        search_filter = or_(
            Employee.name.ilike(f'%{search_query}%'),
            Employee.employee_id.ilike(f'%{search_query}%'),
            Employee.position.ilike(f'%{search_query}%'),
            Employee.email.ilike(f'%{search_query}%')
        )
        query = query.filter(search_filter)

    pagination = query.order_by(Employee.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
    employees_list = pagination.items

    return render_template('employees.html', employees=employees_list, pagination=pagination, search_query=search_query)

@employees_bp.route('/employees/add', methods=['GET', 'POST'], endpoint='employee_add')
@login_required()
def employee_add():
    departments = Department.query.all()

    if request.method == 'POST':
        if not validate_csrf_token(request.form.get('csrf_token')):
            flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
            return redirect(request.url)
        last_employee = Employee.query.order_by(Employee.id.desc()).first()
        if last_employee and last_employee.employee_id:
            try:
                num = int(last_employee.employee_id.replace('EMP', ''))
                new_num = num + 1
            except:
                new_num = last_employee.id + 1
        else:
            new_num = 1
        employee_id = f'EMP{new_num:04d}'

        email_val = request.form.get('email', '').strip() or None
        phone_val = request.form.get('phone', '').strip() or None
        dept_val = request.form.get('department_id') or None

        # تاريخ التوظيف
        hire_date_str = request.form.get('hire_date', '').strip()
        hire_date_val = None
        if hire_date_str:
            try:
                hire_date_val = datetime.strptime(hire_date_str, '%Y-%m-%d').date()
            except:
                hire_date_val = date.today()
        else:
            hire_date_val = date.today()

        if email_val:
            existing_email = Employee.query.filter_by(email=email_val).first()
            if existing_email:
                flash(f'خطأ: البريد الإلكتروني "{email_val}" مستخدم مسبقاً!', 'danger')
                return render_template('employee_add.html', departments=departments)

        # رصيد الإجازات
        annual_leave_balance = request.form.get('annual_leave_balance', type=float) or 0.0
        sick_leave_balance = request.form.get('sick_leave_balance', type=float) or 0.0

        employee = Employee(
            employee_id=employee_id,
            name=request.form.get('name'),
            email=email_val,
            department_id=dept_val,
            position=request.form.get('position'),
            phone=phone_val,
            hire_date=hire_date_val,
            status='active',
            annual_leave_balance=annual_leave_balance,
            sick_leave_balance=sick_leave_balance,
        )
        try:
            db.session.add(employee)
            db.session.commit()
            log_action('create', 'employee', employee.id, f'إضافة موظف: {employee.name} ({employee.employee_id})')
            flash('تم إضافة الموظف بنجاح', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'حدث خطأ أثناء إضافة الموظف: {str(e)}', 'danger')
        return redirect(url_for('employees.employees'))
    return render_template('employee_add.html', departments=departments)

@employees_bp.route('/employees/edit/<int:id>', methods=['GET', 'POST'], endpoint='employee_edit')
@login_required()
def employee_edit(id):
    employee = Employee.query.get_or_404(id)
    departments = Department.query.all()
    if request.method == 'POST':
        if not validate_csrf_token(request.form.get('csrf_token')):
            flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
            return redirect(request.url)
        email_val = request.form.get('email', '').strip() or None
        phone_val = request.form.get('phone', '').strip() or None
        dept_val = request.form.get('department_id') or None

        if email_val:
            existing_email = Employee.query.filter(Employee.email == email_val, Employee.id != id).first()
            if existing_email:
                flash(f'خطأ: البريد الإلكتروني "{email_val}" مستخدم مسبقاً!', 'danger')
                return render_template('employee_edit.html', employee=employee, departments=departments)

        employee.name = request.form.get('name')
        employee.email = email_val
        employee.department_id = dept_val
        employee.position = request.form.get('position')
        employee.phone = phone_val

        # تاريخ التوظيف
        hire_date_str = request.form.get('hire_date', '').strip()
        if hire_date_str:
            try:
                employee.hire_date = datetime.strptime(hire_date_str, '%Y-%m-%d').date()
            except:
                pass  # ما نغيّره لو التاريخ غلط

        # رصيد الإجازات
        employee.annual_leave_balance = request.form.get('annual_leave_balance', type=float) or 0.0
        employee.sick_leave_balance = request.form.get('sick_leave_balance', type=float) or 0.0

        new_status = request.form.get('status')
        old_status = employee.status
        employee.status = new_status

        # ==========================================
        # التعامل مع تعطيل/تفعيل الموظف
        # ==========================================
        if new_status == 'not_active' and old_status == 'active':
            # تعطيل الموظف
            deactivation_reason = request.form.get('deactivation_reason', '')
            deactivation_date_str = request.form.get('deactivation_date', '')

            # حفظ سبب التعطيل
            employee.deactivation_reason = deactivation_reason if deactivation_reason else None

            # حفظ تاريخ التعطيل
            if deactivation_date_str:
                try:
                    employee.deactivation_date = datetime.strptime(deactivation_date_str, '%Y-%m-%d').date()
                except:
                    employee.deactivation_date = date.today()
            else:
                employee.deactivation_date = date.today()

            # إلغاء الإجازات المعلقة تلقائياً
            pending_leaves = Leave.query.filter(
                Leave.employee_id == employee.id,
                Leave.status == 'pending'
            ).all()
            cancelled_count = 0
            for leave in pending_leaves:
                leave.status = 'rejected'
                cancelled_count += 1

            # حذف سجلات الإجازة الموافق عليها المستقبلية (بعد تاريخ التعطيل)
            future_leave_attendance = Attendance.query.filter(
                Attendance.employee_id == employee.id,
                Attendance.status == 'leave',
                Attendance.date >= employee.deactivation_date
            ).all()
            for att in future_leave_attendance:
                # فحص هل الإجازة ما زالت مستمرة
                related_leave = Leave.query.filter(
                    Leave.employee_id == employee.id,
                    Leave.start_date <= att.date,
                    Leave.end_date >= att.date,
                    Leave.status == 'approved'
                ).first()
                if related_leave:
                    # حذف سجل الحضور للإجازة المستقبلية
                    db.session.delete(att)

            try:
                db.session.commit()
                log_msg = f'تعطيل موظف: {employee.name} ({employee.employee_id}) - السبب: {deactivation_reason or "غير محدد"}'
                if cancelled_count > 0:
                    log_msg += f' - تم إلغاء {cancelled_count} إجازة معلقة'
                log_action('update', 'employee', employee.id, log_msg)

                flash_parts = [f'تم تعطيل الموظف: {employee.name}']
                if cancelled_count > 0:
                    flash_parts.append(f'تم إلغاء {cancelled_count} إجازة معلقة تلقائياً')
                flash(' | '.join(flash_parts), 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'حدث خطأ: {str(e)}', 'danger')

        elif new_status == 'active' and old_status == 'not_active':
            # إعادة تفعيل الموظف
            employee.deactivation_reason = None
            # لا نمسح تاريخ التعطيل - للحفاظ على السجل التاريخي
            try:
                db.session.commit()
                log_action('update', 'employee', employee.id, f'إعادة تفعيل موظف: {employee.name} ({employee.employee_id})')
                flash(f'تم إعادة تفعيل الموظف: {employee.name} - يمكنه الآن تسجيل الحضور', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'حدث خطأ: {str(e)}', 'danger')

        else:
            # تعديل عادي بدون تغيير الحالة
            try:
                db.session.commit()
                log_action('update', 'employee', employee.id, f'تعديل موظف: {employee.name} ({employee.employee_id})')
                flash('تم تحديث بيانات الموظف بنجاح', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'حدث خطأ: {str(e)}', 'danger')
        return redirect(url_for('employees.employees'))
    return render_template('employee_edit.html', employee=employee, departments=departments)

@employees_bp.route('/employees/view/<int:id>', endpoint='employee_view')
@login_required()
def employee_view(id):
    employee = Employee.query.get_or_404(id)
    attendance_records = Attendance.query.filter_by(employee_id=id).order_by(Attendance.date.desc()).limit(10).all()
    current_month = datetime.now().month
    current_year = datetime.now().year
    monthly_attendance = Attendance.query.filter(
        Attendance.employee_id == id,
        Attendance.status.in_(['present', 'late']),
        func.extract('month', Attendance.date) == current_month,
        func.extract('year', Attendance.date) == current_year
    ).count()
    leave_days = Attendance.query.filter(
        Attendance.employee_id == id,
        Attendance.status == 'leave',
        func.extract('month', Attendance.date) == current_month,
        func.extract('year', Attendance.date) == current_year
    ).count()

    # بيانات التقويم الشهري
    import calendar
    cal = calendar.monthcalendar(current_year, current_month)
    month_name = calendar.month_name[current_month]

    # خريطة الحالات لكل يوم
    daily_status = {}
    month_records = Attendance.query.filter(
        Attendance.employee_id == id,
        func.extract('month', Attendance.date) == current_month,
        func.extract('year', Attendance.date) == current_year
    ).all()

    for r in month_records:
        day = r.date.day
        status = r.status
        # أولوية: absent > leave > late > present
        priority = {'absent': 4, 'leave': 3, 'late': 2, 'present': 1}
        if day not in daily_status or priority.get(status, 0) > priority.get(daily_status[day], 0):
            daily_status[day] = status

    # ==========================================
    # رصيد الإجازات - حساب المستخدم والمتاح
    # ==========================================
    # حساب إجازات سنوية مستخدمة هذا العام (من خلال عدد الأيام)
    annual_leaves = Leave.query.filter(
        Leave.employee_id == id,
        Leave.leave_type == 'paid',
        Leave.status == 'approved',
        func.extract('year', Leave.start_date) == current_year
    ).all()
    annual_leaves_used = sum((l.end_date - l.start_date).days + 1 for l in annual_leaves)

    # حساب إجازات مرضية مستخدمة هذا العام
    sick_leaves = Leave.query.filter(
        Leave.employee_id == id,
        Leave.leave_type == 'medical',
        Leave.status == 'approved',
        func.extract('year', Leave.start_date) == current_year
    ).all()
    sick_leaves_used = sum((l.end_date - l.start_date).days + 1 for l in sick_leaves)

    # الرصيد المتاح = الرصيد الكلي - المستخدم
    annual_leave_remaining = (employee.annual_leave_balance or 0) - annual_leaves_used
    sick_leave_remaining = (employee.sick_leave_balance or 0) - sick_leaves_used

    return render_template('employee_view.html',
        employee=employee, records=attendance_records,
        monthly_attendance=monthly_attendance, leave_days=leave_days,
        cal=cal, month_name=month_name, current_year=current_year,
        current_month=current_month, daily_status=daily_status,
        today=date.today(),
        annual_leaves_used=annual_leaves_used,
        sick_leaves_used=sick_leaves_used,
        annual_leave_remaining=annual_leave_remaining,
        sick_leave_remaining=sick_leave_remaining)

@employees_bp.route('/employees/delete/<int:id>', methods=['POST'], endpoint='employee_delete')
@login_required()
def employee_delete(id):
    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
        return redirect(request.url)
    employee = Employee.query.get_or_404(id)
    emp_name = employee.name
    emp_id = employee.employee_id
    try:
        # حذف جميع السجلات المرتبطة بالموظف
        Attendance.query.filter_by(employee_id=id).delete()
        Leave.query.filter_by(employee_id=id).delete()
        Task.query.filter_by(employee_id=id).delete()

        # حذف صور الوجه باستخدام المسار المطلق
        if employee.face_image_path:
            image_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', employee.face_image_path)
            if os.path.exists(image_path):
                os.remove(image_path)
            # حذف باقي صور التسجيل
            import glob
            face_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'faces')
            pattern = os.path.join(face_dir, f"{employee.employee_id}_img*.jpg")
            for f in glob.glob(pattern):
                os.remove(f)

        db.session.delete(employee)
        db.session.commit()
        # إلغاء المتجه المؤقت للموظف المحذوف
        update_embedding_cache(id, None, action='delete')
        log_action('delete', 'employee', employee.id, f'حذف موظف: {emp_name} ({emp_id})')
        flash('تم حذف الموظف بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'حدث خطأ: {str(e)}', 'danger')
    return redirect(url_for('employees.employees'))
