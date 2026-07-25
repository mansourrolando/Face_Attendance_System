from flask import Blueprint, render_template, redirect, url_for, session
from datetime import date, datetime, timedelta
from sqlalchemy import func
from instance.models import db, Department, Employee, Attendance, Leave
from utils.helpers import login_required, get_setting
from utils.absence_utils import mark_absent_employees, auto_end_workday
try:
    from config import WEEKEND_DAYS
except ImportError:
    WEEKEND_DAYS = '4,5'  # الجمعة والسبت كقيمة افتراضية

def _get_weekend_days():
    """جلب أيام العطلة الأسبوعية من الإعدادات"""
    weekend_str = get_setting('weekend_days', WEEKEND_DAYS)
    try:
        return tuple(int(d.strip()) for d in weekend_str.split(','))
    except:
        return (4, 5)

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/dashboard', endpoint='dashboard')
@login_required()
def dashboard():
    today = date.today()

    # تسجيل غياب تلقائي للأمس
    yesterday = today - timedelta(days=1)
    if yesterday.weekday() not in _get_weekend_days():  # تخطي أيام العطلة
        mark_absent_employees(yesterday)

    # إنهاء يوم العمل تلقائياً
    auto_end_result = auto_end_workday()

    total_employees = Employee.query.filter_by(status='active').count()

    # === استعلام واحد لجلب كل إحصائيات اليوم (محسّن) ===
    today_stats_raw = db.session.query(
        Attendance.status,
        func.count(Attendance.id)
    ).filter(
        Attendance.date == today
    ).join(
        Employee, Attendance.employee_id == Employee.id
    ).filter(
        Employee.status == 'active'
    ).group_by(Attendance.status).all()

    today_stats = dict(today_stats_raw)
    present_today = today_stats.get('present', 0) + today_stats.get('late', 0)
    late_today = today_stats.get('late', 0)
    ontime_today = today_stats.get('present', 0)
    leave_today = today_stats.get('leave', 0)
    absent_today = today_stats.get('absent', 0)

    # الموظفون الذين لم يسجّلوا بعد
    recorded_today = db.session.query(
        Attendance.employee_id
    ).filter(
        Attendance.date == today
    ).join(
        Employee, Attendance.employee_id == Employee.id
    ).filter(
        Employee.status == 'active'
    ).distinct().all()
    recorded_ids = {r.employee_id for r in recorded_today}
    not_recorded = total_employees - len(recorded_ids)

    stats = {
        'total_employees': total_employees,
        'present_today': present_today,
        'leave_today': leave_today,
        'absent_today': absent_today,
        'not_recorded': not_recorded,
        'total_departments': Department.query.count(),
        'early_checkouts_today': Attendance.query.filter(
            Attendance.date == today,
            Attendance.early_checkout == True
        ).join(Employee).filter(Employee.status == 'active').count()
    }

    recent_attendance = Attendance.query.filter_by(date=today).join(
        Employee, Attendance.employee_id == Employee.id
    ).filter(Employee.status == 'active').order_by(Attendance.time_in.desc()).limit(10).all()

    # === بيانات الرسم الدائري ===
    attendance_chart = {
        'present': ontime_today,
        'late': late_today,
        'leave': leave_today,
        'absent': absent_today,
        'not_recorded': max(0, not_recorded)
    }

    # === بيانات الأقسام ===
    departments_data = []
    departments_list = Department.query.all()
    for dept in departments_list:
        emp_count = Employee.query.filter_by(department_id=dept.id, status='active').count()
        if emp_count > 0:
            departments_data.append({'name': dept.name, 'count': emp_count})

    # === بيانات الشهر - استعلام واحد بدل 4 (محسّن) ===
    current_month = today.month
    current_year = today.year

    month_stats_raw = db.session.query(
        Attendance.status,
        func.count(Attendance.id)
    ).filter(
        func.extract('month', Attendance.date) == current_month,
        func.extract('year', Attendance.date) == current_year
    ).join(
        Employee, Attendance.employee_id == Employee.id
    ).filter(
        Employee.status == 'active'
    ).group_by(Attendance.status).all()

    month_stats = dict(month_stats_raw)
    month_ontime = month_stats.get('present', 0)
    month_late = month_stats.get('late', 0)
    month_leave = month_stats.get('leave', 0)
    month_absent = month_stats.get('absent', 0)

    total_records_month = month_ontime + month_late + month_leave + month_absent
    if total_records_month == 0:
        total_records_month = 1

    monthly_pct = {
        'present': round((month_ontime / total_records_month) * 100, 1),
        'late': round((month_late / total_records_month) * 100, 1),
        'leave': round((month_leave / total_records_month) * 100, 1),
        'absent': round((month_absent / total_records_month) * 100, 1),
        'present_count': month_ontime,
        'late_count': month_late,
        'leave_count': month_leave,
        'absent_count': month_absent,
        'attendance_rate': round(((month_ontime + month_late) / total_records_month) * 100, 1),
        'absence_rate': round(((month_absent) / total_records_month) * 100, 1),
    }

    return render_template('dashboard.html',
        stats=stats,
        recent_attendance=recent_attendance,
        attendance_chart=attendance_chart,
        departments_data=departments_data,
        monthly_pct=monthly_pct,
        current_month_name=today.strftime('%B %Y')
    )
