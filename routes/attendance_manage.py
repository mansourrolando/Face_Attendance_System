"""
إدارة الحضور يدوياً - إضافة وتعديل سجلات الحضور من قبل المدير
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, date, time as dt_time, timedelta
from instance.models import db, Employee, Department, Attendance, Leave, Holiday
from utils.helpers import log_action, login_required, get_setting, format_work_hours, format_minutes, _calc_work_hours
from utils.csrf import validate_csrf_token
from config import *

attendance_manage_bp = Blueprint('attendance_manage', __name__)


@attendance_manage_bp.route('/attendance/add', methods=['GET', 'POST'], endpoint='attendance_add')
@login_required()
def attendance_add():
    """إضافة سجل حضور يدوي من قبل المدير"""
    employees = Employee.query.filter_by(status='active').order_by(Employee.name).all()

    if request.method == 'POST':
        if not validate_csrf_token(request.form.get('csrf_token')):
            flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
            return redirect(request.url)

        emp_id = request.form.get('employee_id')
        date_str = request.form.get('date')
        time_in_str = request.form.get('time_in')
        time_out_str = request.form.get('time_out')
        status = request.form.get('status', 'present')
        notes = request.form.get('notes', '').strip()

        try:
            emp_id = int(emp_id)
        except (ValueError, TypeError):
            flash('خطأ في اختيار الموظف', 'danger')
            return redirect(request.url)

        try:
            att_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except:
            flash('تاريخ غير صالح', 'danger')
            return redirect(request.url)

        # فحص هل يوجد سجل حضور لهذا الموظف في هذا اليوم
        existing = Attendance.query.filter_by(employee_id=emp_id, date=att_date).first()
        if existing:
            flash(f'يوجد سجل حضور لهذا الموظف في تاريخ {date_str} بالفعل! يمكنك تعديله بدلاً من ذلك.', 'danger')
            return redirect(request.url)

        # تحويل الأوقات
        time_in = None
        time_out = None
        if time_in_str:
            try:
                time_in = datetime.strptime(time_in_str, '%H:%M').time()
            except:
                pass
        if time_out_str:
            try:
                time_out = datetime.strptime(time_out_str, '%H:%M').time()
            except:
                pass

        # حساب دقائق التأخير
        late_mins = 0
        employee = Employee.query.get(emp_id)
        work_start_str = get_setting('work_start', WORK_START_TIME)
        grace_str = get_setting('grace_period', str(GRACE_PERIOD_MINUTES))
        
        try:
            start_h, start_m = map(int, work_start_str.split(':'))
            grace = int(grace_str) if grace_str.isdigit() else GRACE_PERIOD_MINUTES
            start_time = dt_time(start_h, start_m)
        except:
            start_time = dt_time(8, 0)
            grace = GRACE_PERIOD_MINUTES

        if time_in and status in ('present', 'late'):
            allowed_time = (datetime.combine(att_date, start_time) + timedelta(minutes=grace)).time()
            if time_in > allowed_time:
                status = 'late'
                diff = datetime.combine(att_date, time_in) - datetime.combine(att_date, allowed_time)
                late_mins = int(diff.total_seconds() / 60)
            else:
                status = 'present'
                late_mins = 0

        # حساب ساعات العمل
        work_hours = None
        if time_in and time_out:
            dt_in = datetime.combine(att_date, time_in)
            dt_out = datetime.combine(att_date, time_out)
            total_seconds = (dt_out - dt_in).total_seconds()
            if total_seconds > 0:
                work_hours = round(total_seconds / 3600, 2)

        # حساب الخروج المبكر
        early_checkout = False
        early_checkout_mins = 0
        work_end_str = get_setting('work_end', WORK_END_TIME)
        
        try:
            end_h, end_m = map(int, work_end_str.split(':'))
            work_end_time = dt_time(end_h, end_m)
        except:
            work_end_time = dt_time(17, 0)

        if time_out and time_out < work_end_time and status in ('present', 'late'):
            early_checkout = True
            diff = datetime.combine(att_date, work_end_time) - datetime.combine(att_date, time_out)
            early_checkout_mins = int(diff.total_seconds() / 60)

        # حساب الغياب
        absence_type = None
        if status == 'absent':
            absence_type = request.form.get('absence_type', 'unjustified')

        attendance = Attendance(
            employee_id=emp_id,
            date=att_date,
            time_in=time_in,
            time_out=time_out,
            status=status,
            late_minutes=late_mins,
            work_hours=work_hours,
            early_checkout=early_checkout,
            early_checkout_minutes=early_checkout_mins,
            absence_type=absence_type,
            notes=notes if notes else None
        )
        db.session.add(attendance)
        db.session.commit()

        emp_name = employee.name if employee else '?'
        log_action('create', 'attendance', attendance.id, f'إضافة حضور يدوي: {emp_name} - {date_str} ({status})')
        flash(f'تم إضافة سجل الحضور لـ {emp_name} بنجاح', 'success')
        return redirect(url_for('attendance.attendance_page'))

    work_start = get_setting('work_start', WORK_START_TIME)
    work_end = get_setting('work_end', WORK_END_TIME)
    grace_period = get_setting('grace_period', str(GRACE_PERIOD_MINUTES))

    return render_template('attendance_add.html',
        employees=employees,
        work_start=work_start,
        work_end=work_end,
        grace_period=grace_period
    )


@attendance_manage_bp.route('/attendance/edit/<int:id>', methods=['GET', 'POST'], endpoint='attendance_edit')
@login_required()
def attendance_edit(id):
    """تعديل سجل حضور يدوياً من قبل المدير"""
    record = Attendance.query.get_or_404(id)
    employees = Employee.query.filter_by(status='active').order_by(Employee.name).all()

    if request.method == 'POST':
        if not validate_csrf_token(request.form.get('csrf_token')):
            flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
            return redirect(request.url)

        # حفظ القيم القديمة للمقارنة
        old_status = record.status
        old_time_in = record.time_in
        old_time_out = record.time_out

        # تحديث البيانات
        time_in_str = request.form.get('time_in')
        time_out_str = request.form.get('time_out')
        status = request.form.get('status', record.status)
        notes = request.form.get('notes', '').strip()

        # تحويل الأوقات
        if time_in_str:
            try:
                record.time_in = datetime.strptime(time_in_str, '%H:%M').time()
            except:
                pass
        else:
            record.time_in = None

        if time_out_str:
            try:
                record.time_out = datetime.strptime(time_out_str, '%H:%M').time()
            except:
                pass
        else:
            record.time_out = None

        record.status = status
        record.notes = notes if notes else None

        # حساب دقائق التأخير
        employee = Employee.query.get(record.employee_id)
        work_start_str = get_setting('work_start', WORK_START_TIME)
        grace_str = get_setting('grace_period', str(GRACE_PERIOD_MINUTES))
        
        try:
            start_h, start_m = map(int, work_start_str.split(':'))
            grace = int(grace_str) if grace_str.isdigit() else GRACE_PERIOD_MINUTES
            start_time = dt_time(start_h, start_m)
        except:
            start_time = dt_time(8, 0)
            grace = GRACE_PERIOD_MINUTES

        if record.time_in and status in ('present', 'late'):
            allowed_time = (datetime.combine(record.date, start_time) + timedelta(minutes=grace)).time()
            if record.time_in > allowed_time:
                record.status = 'late'
                diff = datetime.combine(record.date, record.time_in) - datetime.combine(record.date, allowed_time)
                record.late_minutes = int(diff.total_seconds() / 60)
            else:
                if record.status == 'late':
                    record.status = 'present'
                record.late_minutes = 0
        else:
            record.late_minutes = 0

        # إعادة حساب ساعات العمل
        if record.time_in and record.time_out:
            dt_in = datetime.combine(record.date, record.time_in)
            dt_out = datetime.combine(record.date, record.time_out)
            total_seconds = (dt_out - dt_in).total_seconds()
            if total_seconds > 0:
                # خصم وقت الإجازة الساعية
                if record.leave_out and record.leave_in:
                    dt_leave_out = datetime.combine(record.date, record.leave_out)
                    dt_leave_in = datetime.combine(record.date, record.leave_in)
                    leave_seconds = (dt_leave_in - dt_leave_out).total_seconds()
                    if leave_seconds > 0:
                        total_seconds -= leave_seconds
                record.work_hours = round(total_seconds / 3600, 2)
            else:
                record.work_hours = 0
        else:
            record.work_hours = None

        # إعادة حساب الخروج المبكر
        work_end_str = get_setting('work_end', WORK_END_TIME)
        
        try:
            end_h, end_m = map(int, work_end_str.split(':'))
            work_end_time = dt_time(end_h, end_m)
        except:
            work_end_time = dt_time(17, 0)

        if record.time_out and record.time_out < work_end_time and record.status in ('present', 'late'):
            record.early_checkout = True
            diff = datetime.combine(record.date, work_end_time) - datetime.combine(record.date, record.time_out)
            record.early_checkout_minutes = int(diff.total_seconds() / 60)
        else:
            record.early_checkout = False
            record.early_checkout_minutes = 0

        # معالجة الغياب
        if status == 'absent':
            record.absence_type = request.form.get('absence_type', 'unjustified')
            record.time_in = None
            record.time_out = None
            record.work_hours = None
            record.late_minutes = 0
            record.early_checkout = False
            record.early_checkout_minutes = 0
        else:
            record.absence_type = None

        db.session.commit()

        emp_name = employee.name if employee else '?'
        log_action('update', 'attendance', record.id, f'تعديل حضور: {emp_name} - {record.date} ({old_status} -> {record.status})')
        flash(f'تم تعديل سجل الحضور لـ {emp_name} بنجاح', 'success')
        return redirect(url_for('reports.reports'))

    # GET - عرض صفحة التعديل
    work_start = get_setting('work_start', WORK_START_TIME)
    work_end = get_setting('work_end', WORK_END_TIME)
    grace_period = get_setting('grace_period', str(GRACE_PERIOD_MINUTES))

    return render_template('attendance_edit.html',
        record=record,
        employees=employees,
        work_start=work_start,
        work_end=work_end,
        grace_period=grace_period
    )


@attendance_manage_bp.route('/attendance/delete/<int:id>', methods=['POST'], endpoint='attendance_delete')
@login_required()
def attendance_delete(id):
    """حذف سجل حضور"""
    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
        return redirect(url_for('reports.reports'))

    record = Attendance.query.get_or_404(id)
    emp_name = record.employee.name if record.employee else '?'
    att_date = record.date

    db.session.delete(record)
    db.session.commit()

    log_action('delete', 'attendance', id, f'حذف حضور: {emp_name} - {att_date}')
    flash(f'تم حذف سجل الحضور لـ {emp_name} بتاريخ {att_date}', 'success')
    return redirect(url_for('reports.reports'))
