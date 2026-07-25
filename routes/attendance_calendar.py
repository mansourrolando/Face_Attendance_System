"""
تقويم الحضور المرئي - عرض حالة حضور الموظفين على شكل تقويم شهري
"""
from flask import Blueprint, render_template, request
from datetime import datetime, date, timedelta
from sqlalchemy import func
import calendar
from instance.models import db, Employee, Department, Attendance, Holiday
from utils.helpers import login_required, get_setting
from utils.absence_utils import mark_absent_employees
from config import WEEKEND_DAYS

attendance_calendar_bp = Blueprint('attendance_calendar', __name__)


def _get_weekend_days():
    """جلب أيام العطلة الأسبوعية من الإعدادات"""
    weekend_str = get_setting('weekend_days', WEEKEND_DAYS)
    try:
        return tuple(int(d.strip()) for d in weekend_str.split(','))
    except:
        return (4, 5)


@attendance_calendar_bp.route('/attendance/calendar', endpoint='attendance_calendar')
@login_required()
def calendar_view():
    """عرض تقويم الحضور الشهري"""
    # جلب المعاملات
    selected_year = request.args.get('year', date.today().year, type=int)
    selected_month = request.args.get('month', date.today().month, type=int)
    selected_employee = request.args.get('employee_id', None, type=int)
    selected_department = request.args.get('department_id', None, type=int)

    if selected_month < 1:
        selected_month = 1
    if selected_month > 12:
        selected_month = 12

    # الشهر السابق والتالي
    if selected_month == 1:
        prev_month, prev_year = 12, selected_year - 1
    else:
        prev_month, prev_year = selected_month - 1, selected_year
    if selected_month == 12:
        next_month, next_year = 1, selected_year + 1
    else:
        next_month, next_year = selected_month + 1, selected_year

    # جلب الموظفين والأقسام
    employees_query = Employee.query.filter_by(status='active')
    if selected_department:
        employees_query = employees_query.filter_by(department_id=selected_department)
    employees = employees_query.order_by(Employee.name).all()
    departments = Department.query.all()

    if selected_employee:
        target = Employee.query.get(selected_employee)
        target_employees = [target] if target else employees
    else:
        target_employees = employees

    num_days = calendar.monthrange(selected_year, selected_month)[1]
    month_days = list(range(1, num_days + 1))

    month_names_ar = {
        1: 'يناير', 2: 'فبراير', 3: 'مارس', 4: 'أبريل',
        5: 'مايو', 6: 'يونيو', 7: 'يوليو', 8: 'أغسطس',
        9: 'سبتمبر', 10: 'أكتوبر', 11: 'نوفمبر', 12: 'ديسمبر'
    }

    today = date.today()
    start_date = date(selected_year, selected_month, 1)
    end_date = date(selected_year, selected_month, num_days)

    # تسجيل غياب تلقائي
    if start_date < today:
        mark_absent_employees(start_date)

    # جلب سجلات الحضور
    attendance_map = {}
    records = Attendance.query.filter(
        Attendance.date >= start_date,
        Attendance.date <= end_date
    ).all()
    for r in records:
        attendance_map[(r.employee_id, r.date.day)] = r

    # جلب العطل الرسمية
    holidays = Holiday.query.filter(
        db.or_(
            db.and_(
                db.extract('year', Holiday.date) == selected_year,
                db.extract('month', Holiday.date) == selected_month
            ),
            Holiday.is_recurring == True
        )
    ).all()
    holiday_days = {}
    for h in holidays:
        if h.date.month == selected_month and h.date.year == selected_year:
            holiday_days[h.date.day] = h.name
        elif h.is_recurring and h.date.month == selected_month:
            try:
                recurring_date = h.date.replace(year=selected_year)
                if recurring_date.month == selected_month:
                    holiday_days[recurring_date.day] = h.name
            except ValueError:
                pass

    # بناء بيانات التقويم
    calendar_data = []
    for emp in target_employees:
        emp_data = {
            'employee': emp,
            'days': [],
            'summary': {'present': 0, 'late': 0, 'absent': 0, 'leave': 0, 'total_hours': 0, 'total_late_minutes': 0, 'early_checkouts': 0}
        }

        for day in month_days:
            current_date = date(selected_year, selected_month, day)
            day_info = {
                'day': day, 'date': current_date,
                'is_weekend': current_date.weekday() in _get_weekend_days(),
                'is_holiday': day in holiday_days,
                'holiday_name': holiday_days.get(day, ''),
                'is_future': current_date > today,
                'status': None, 'time_in': None, 'time_out': None,
                'work_hours': None, 'late_minutes': 0, 'early_checkout': False,
            }

            record = attendance_map.get((emp.id, day))
            if record:
                day_info['status'] = record.status
                day_info['time_in'] = record.time_in
                day_info['time_out'] = record.time_out
                day_info['work_hours'] = record.work_hours
                day_info['late_minutes'] = record.late_minutes or 0
                day_info['early_checkout'] = record.early_checkout or False

                if record.status == 'present':
                    emp_data['summary']['present'] += 1
                elif record.status == 'late':
                    emp_data['summary']['late'] += 1
                elif record.status == 'absent':
                    emp_data['summary']['absent'] += 1
                elif record.status == 'leave':
                    emp_data['summary']['leave'] += 1
                if record.work_hours:
                    emp_data['summary']['total_hours'] += record.work_hours
                emp_data['summary']['total_late_minutes'] += day_info['late_minutes']
                if record.early_checkout:
                    emp_data['summary']['early_checkouts'] += 1

            emp_data['days'].append(day_info)
        calendar_data.append(emp_data)

    return render_template('attendance_calendar.html',
        calendar_data=calendar_data, selected_year=selected_year, selected_month=selected_month,
        selected_employee=selected_employee, selected_department=selected_department,
        month_name=month_names_ar.get(selected_month, ''), month_days=month_days,
        employees=employees, departments=departments,
        prev_month=prev_month, prev_year=prev_year, next_month=next_month, next_year=next_year,
        today=today, holiday_days=holiday_days)
