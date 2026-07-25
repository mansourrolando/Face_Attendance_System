"""
أدوات تسجيل الغياب التلقائي
وظيفة: تسجيل غياب الموظفين الذين لم يسجلوا حضور في يوم معين
         إنهاء يوم العمل تلقائياً بعد انتهاء الدوام
         الخصم التلقائي من رصيد الإجازات عند الغياب
"""
from datetime import date, datetime, time as dt_time, timedelta
from instance.models import db, Employee, Attendance, Leave, Holiday, Setting
from utils.helpers import get_setting
try:
    from config import WEEKEND_DAYS
except ImportError:
    WEEKEND_DAYS = '4,5'  # الجمعة والسبت كقيمة افتراضية


def _deduct_leave_balance(employee, days=1):
    """خصم من رصيد الإجازات السنوية للموظف"""
    if employee.annual_leave_balance and employee.annual_leave_balance > 0:
        employee.annual_leave_balance = max(0, employee.annual_leave_balance - days)
        return True, 'annual'
    elif employee.sick_leave_balance and employee.sick_leave_balance > 0:
        employee.sick_leave_balance = max(0, employee.sick_leave_balance - days)
        return True, 'sick'
    return False, None


def mark_absent_employees(target_date, allow_today=False):
    """
    تسجيل غياب الموظفين النشطين الذين لم يسجلوا حضور في تاريخ معين.
    
    القواعد:
    - يسجّل غياب فقط للموظفين النشطين (status='active')
    - لا يسجّل غياب إذا كان الموظف عنده إجازة يوم كامل موافق عليها
    - لا يسجّل غياب إذا كان عندو سجل حضور فعلاً
    - لا يسجّل غياب لليوم الحالي إلا إذا allow_today=True
    - لا يسجّل غياب قبل تاريخ توظيف الموظف
    - لا يسجّل غياب في عطلة نهاية الأسبوع (الجمعة والسبت)
    - لا يسجّل غياب في العطل الرسمية
    - الغياب المسجّل يكون 'غير مبرر' بشكل افتراضي
    - خصم تلقائي من رصيد الإجازات إذا وجد (تحويل إلى غياب مبرر)
    """
    today = date.today()
    
    if target_date > today:
        return {'marked': 0, 'skipped_leave': 0, 'skipped_existing': 0,
                'skipped_inactive': 0, 'skipped_before_hire': 0, 'skipped_weekend': 0, 'skipped_holiday': 0, 'deducted_balance': 0}
    
    if target_date == today and not allow_today:
        return {'marked': 0, 'skipped_leave': 0, 'skipped_existing': 0,
                'skipped_inactive': 0, 'skipped_before_hire': 0, 'skipped_weekend': 0, 'skipped_holiday': 0, 'deducted_balance': 0}
    
    # جلب أيام العطلة الأسبوعية من الإعدادات
    weekend_str = get_setting('weekend_days', WEEKEND_DAYS)
    try:
        weekend = tuple(int(d.strip()) for d in weekend_str.split(','))
    except:
        weekend = (4, 5)  # الجمعة والسبت كقيمة افتراضية

    if target_date.weekday() in weekend:
        return {'marked': 0, 'skipped_leave': 0, 'skipped_existing': 0,
                'skipped_inactive': 0, 'skipped_before_hire': 0, 'skipped_weekend': 1, 'skipped_holiday': 0, 'deducted_balance': 0}
    
    holiday = Holiday.is_holiday(target_date)
    if holiday:
        return {'marked': 0, 'skipped_leave': 0, 'skipped_existing': 0,
                'skipped_inactive': 0, 'skipped_before_hire': 0, 'skipped_weekend': 0, 'skipped_holiday': 1, 'deducted_balance': 0}
    
    all_employees = Employee.query.all()
    
    result = {'marked': 0, 'skipped_leave': 0, 'skipped_existing': 0,
              'skipped_inactive': 0, 'skipped_before_hire': 0, 'skipped_weekend': 0,
              'skipped_holiday': 0, 'deducted_balance': 0}
    
    for emp in all_employees:
        if emp.status != 'active':
            result['skipped_inactive'] += 1
            continue
        
        if emp.hire_date and target_date < emp.hire_date:
            result['skipped_before_hire'] += 1
            continue
        
        existing = Attendance.query.filter_by(employee_id=emp.id, date=target_date).first()
        if existing:
            result['skipped_existing'] += 1
            continue
        
        approved_leave = Leave.query.filter(
            Leave.employee_id == emp.id,
            Leave.start_date <= target_date,
            Leave.end_date >= target_date,
            Leave.status == 'approved',
            Leave.leave_type != 'hourly'
        ).first()
        
        if approved_leave:
            attendance = Attendance(
                employee_id=emp.id, date=target_date, status='leave',
                notes=f'إجازة {approved_leave.leave_type}'
            )
            db.session.add(attendance)
            result['skipped_leave'] += 1
            continue
        
        # غياب غير مبرر - الرصيد لا يُخصم تلقائياً
        # الخصم يتم فقط عند تقديم طلب إجازة معتمد
        absence = Attendance(
            employee_id=emp.id, date=target_date, status='absent',
            absence_type='unjustified', notes='غياب غير مبرر - لم يسجّل حضور'
        )
        db.session.add(absence)
        result['marked'] += 1
    
    if result['marked'] > 0 or result['skipped_leave'] > 0:
        db.session.commit()
    
    return result


def is_non_working_day(target_date):
    """فحص هل التاريخ هو يوم غير عمل"""
    weekend_str = get_setting('weekend_days', WEEKEND_DAYS)
    try:
        weekend = tuple(int(d.strip()) for d in weekend_str.split(','))
    except:
        weekend = (4, 5)
    if target_date.weekday() in weekend:
        return True, 'عطلة نهاية الأسبوع'
    holiday = Holiday.is_holiday(target_date)
    if holiday:
        return True, f'عطلة رسمية: {holiday.name}'
    return False, None


def _get_auto_checkout_time(work_end_time_str='17:00'):
    """حساب وقت الانصراف التلقائي (نهاية الدوام + ساعات إضافية)"""
    from config import AUTO_CHECKOUT_AFTER_HOURS

    auto_after = int(get_setting('auto_checkout_after_hours', str(AUTO_CHECKOUT_AFTER_HOURS)))
    try:
        end_hour, end_minute = map(int, work_end_time_str.split(':'))
        total_minutes = (end_hour * 60 + end_minute) + (auto_after * 60)
        # معالجة الساعات بعد منتصف الليل
        if total_minutes >= 24 * 60:
            total_minutes = total_minutes % (24 * 60)
        checkout_hour = total_minutes // 60
        checkout_minute = total_minutes % 60
        return dt_time(checkout_hour, checkout_minute)
    except:
        return dt_time(18, 0)


def process_forgot_checkouts(target_date, work_end_time_str='17:00'):
    """معالجة الموظفين الذين سجّلوا حضوراً ولم يسجّلوا انصرافاً"""
    from config import AUTO_CHECKOUT_ENABLED

    # فحص هل الانصراف التلقائي مفعّل
    auto_enabled = get_setting('auto_checkout_enabled', str(AUTO_CHECKOUT_ENABLED))
    if auto_enabled.lower() in ('false', '0', 'no'):
        return 0

    # حساب وقت الانصراف التلقائي (مع معالجة الساعات بعد منتصف الليل)
    auto_checkout_time = _get_auto_checkout_time(work_end_time_str)

    records = Attendance.query.filter(
        Attendance.date == target_date,
        Attendance.time_in.isnot(None),
        Attendance.time_out.is_(None),
        Attendance.status.in_(['present', 'late'])
    ).all()

    count = 0
    for rec in records:
        rec.time_out = auto_checkout_time
        rec.checkout_auto = True
        # حساب ساعات العمل
        from datetime import datetime as dt, date as d
        if rec.time_in:
            dt_in = dt.combine(d.today(), rec.time_in)
            dt_out = dt.combine(d.today(), auto_checkout_time)
            total_seconds = (dt_out - dt_in).total_seconds()
            if total_seconds > 0:
                rec.work_hours = round(total_seconds / 3600, 2)
        rec.notes = (rec.notes or '') + ' | انصراف تلقائي - لم يسجّل انصراف'
        count += 1

    if count > 0:
        db.session.commit()

    return count


def auto_end_workday():
    """إنهاء يوم العمل تلقائياً بعد وقت الانصراف التلقائي (نهاية الدوام + ساعات إضافية)"""
    today = date.today()
    now = datetime.now()

    # جلب أيام العطلة من الإعدادات
    weekend_str = get_setting('weekend_days', WEEKEND_DAYS)
    try:
        weekend = tuple(int(d.strip()) for d in weekend_str.split(','))
    except:
        weekend = (4, 5)

    if today.weekday() in weekend:
        return None

    holiday = Holiday.is_holiday(today)
    if holiday:
        return None

    workday_key = f'workday_ended_{today.isoformat()}'
    already_ended = Setting.query.filter_by(key=workday_key).first()
    if already_ended:
        return None

    from config import WORK_END_TIME
    work_end_setting = get_setting('work_end', WORK_END_TIME)
    try:
        end_hour, end_minute = map(int, work_end_setting.split(':'))
    except:
        end_hour, end_minute = map(int, WORK_END_TIME.split(':'))

    # حساب وقت الانصراف التلقائي (نهاية الدوام + ساعات إضافية)
    auto_checkout_time = _get_auto_checkout_time(work_end_setting)

    # الانتظار حتى وقت الانصراف التلقائي وليس مجرد نهاية الدوام
    if now.time() < auto_checkout_time:
        return None

    result = {'forgot_checkouts': 0, 'absent_marked': 0, 'leave_marked': 0}

    result['forgot_checkouts'] = process_forgot_checkouts(today, work_end_setting)

    absent_result = mark_absent_employees(today, allow_today=True)
    result['absent_marked'] = absent_result.get('marked', 0)
    result['leave_marked'] = absent_result.get('skipped_leave', 0)

    ended_flag = Setting(key=workday_key, value=now.strftime('%Y-%m-%d %H:%M:%S'))
    db.session.add(ended_flag)
    db.session.commit()

    return result