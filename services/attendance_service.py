"""
خدمة الحضور المشتركة - تستخدم من kiosk.py و attendance.py
تحتوي على منطق تسجيل الحضور والانصراف والإجازة الساعية
+ حساب ساعات العمل، دقائق التأخير، والخروج المبكر
"""
from datetime import datetime, date, time, timedelta
from instance.models import db, Employee, Attendance, Leave, Holiday
from utils.face_utils import process_face_image, find_best_match
from utils.helpers import get_setting, _calc_work_hours
from config import *


def _parse_time_setting(value_str, default_str):
    """تحليل إعداد الوقت مع fallback"""
    try:
        h, m = map(int, value_str.split(':'))
        return h, m
    except:
        return map(int, default_str.split(':'))


def _get_work_time_settings(employee=None):
    """جلب إعدادات أوقات العمل من قاعدة البيانات"""
    work_start = get_setting('work_start', WORK_START_TIME)
    work_end = get_setting('work_end', WORK_END_TIME)
    start_h, start_m = _parse_time_setting(work_start, WORK_START_TIME)
    end_h, end_m = _parse_time_setting(work_end, WORK_END_TIME)

    grace_period = get_setting('grace_period', str(GRACE_PERIOD_MINUTES))
    earliest_time = get_setting('attendance_earliest_time', ATTENDANCE_EARLIEST_TIME)

    grace = int(grace_period) if grace_period.isdigit() else GRACE_PERIOD_MINUTES
    earliest_h, earliest_m = _parse_time_setting(earliest_time, ATTENDANCE_EARLIEST_TIME)

    return {
        'start_hour': start_h, 'start_minute': start_m,
        'end_hour': end_h, 'end_minute': end_m,
        'grace_period': grace,
        'earliest_hour': earliest_h, 'earliest_minute': earliest_m,
        'work_start': f'{start_h:02d}:{start_m:02d}',
        'work_end': f'{end_h:02d}:{end_m:02d}',
    }


def _calculate_late_minutes(current_time, start_time, grace_period):
    """حساب دقائق التأخير بعد فترة السماح"""
    allowed_time = (datetime.combine(date.today(), start_time) + timedelta(minutes=grace_period)).time()
    if current_time > allowed_time:
        diff = datetime.combine(date.today(), current_time) - datetime.combine(date.today(), allowed_time)
        return int(diff.total_seconds() / 60)
    return 0


def _calculate_work_hours_float(time_in, time_out, leave_out=None, leave_in=None):
    """حساب ساعات العمل الفعلية بالعشرية (مع خصم وقت الإجازة الساعية)"""
    if not time_in or not time_out:
        return None
    dt_in = datetime.combine(date.today(), time_in)
    dt_out = datetime.combine(date.today(), time_out)
    total_seconds = (dt_out - dt_in).total_seconds()
    if total_seconds <= 0:
        return 0
    # خصم وقت الإجازة الساعية
    if leave_out and leave_in:
        dt_leave_out = datetime.combine(date.today(), leave_out)
        dt_leave_in = datetime.combine(date.today(), leave_in)
        leave_seconds = (dt_leave_in - dt_leave_out).total_seconds()
        if leave_seconds > 0:
            total_seconds -= leave_seconds
    return round(total_seconds / 3600, 2)


def _calculate_early_checkout_minutes(time_out, work_end_time):
    """حساب دقائق الخروج المبكر"""
    if not time_out or not work_end_time:
        return 0
    if time_out < work_end_time:
        diff = datetime.combine(date.today(), work_end_time) - datetime.combine(date.today(), time_out)
        return int(diff.total_seconds() / 60)
    return 0


def verify_face_from_image(img):
    """
    التحقق من الوجه من صورة - الخطوة المشتركة الأولى
    يعيد: (success, result_dict)
    - إذا نجح: result_dict = {best_match, best_score, emp_info}
    - إذا فشل: result_dict = {message: error_text}
    """
    success, message, input_embedding = process_face_image(img)

    if not success:
        return False, {'message': message}

    best_match, best_score, match_message = find_best_match(input_embedding)

    if not best_match:
        return False, {'message': match_message}

    # فحص حالة الموظف
    if best_match.status != 'active':
        return False, {
            'message': f'حسابك غير نشط ({best_match.name}) - تواصل مع الإدارة لتفعيل حسابك'
        }

    emp_info = {
        'name': best_match.name,
        'employee_id': best_match.employee_id,
        'department': best_match.department.name if best_match.department else '-',
        'position': best_match.position or '-',
        'photo': best_match.face_image_path or '',
    }

    return True, {
        'best_match': best_match,
        'best_score': best_score,
        'emp_info': emp_info,
    }


def register_checkin(employee, emp_info, best_score, settings=None):
    """
    تسجيل حضور - ينشئ سجل حضور جديد
    يدعم: حساب دقائق التأخير، حساب ساعات العمل، الخروج المبكر
    يرجع: dict مع success ونتيجة العملية
    """
    # استخدام إعدادات الموظف المخصصة إذا لم يتم تمرير إعدادات
    if settings is None:
        settings = _get_work_time_settings(employee)

    now = datetime.now()
    today = now.date()
    current_time = now.time()

    # فحص هل اليوم عطلة رسمية
    today_holiday = Holiday.is_holiday(today)
    if today_holiday:
        return {
            'success': False,
            'message': f'اليوم عطلة رسمية: {today_holiday.name}'
        }

    # فحص إجازة يوم كامل
    is_on_full_leave = Leave.query.filter(
        Leave.employee_id == employee.id,
        Leave.start_date <= today,
        Leave.end_date >= today,
        Leave.status == 'approved',
        Leave.leave_type != 'hourly'
    ).first()

    if is_on_full_leave:
        return {
            'success': False,
            'message': f'أنت في إجازة رسمية من {is_on_full_leave.start_date} إلى {is_on_full_leave.end_date}'
        }

    # فحص هل عندو سجل حضور اليوم
    existing = Attendance.query.filter_by(employee_id=employee.id, date=today).first()

    if existing:
        if existing.time_out is None:
            # تسجيل انصراف
            existing.time_out = current_time

            # حساب ساعات العمل الفعلية
            existing.work_hours = _calculate_work_hours_float(
                existing.time_in, current_time,
                existing.leave_out, existing.leave_in
            )

            # حساب الخروج المبكر
            work_end_time = time(settings['end_hour'], settings['end_minute'])
            early_minutes = _calculate_early_checkout_minutes(current_time, work_end_time)
            if early_minutes > 0:
                existing.early_checkout = True
                existing.early_checkout_minutes = early_minutes

            db.session.commit()
            work_hours_str = _calc_work_hours(existing.time_in, current_time)

            result = {
                'success': True,
                'name': employee.name,
                'time': now.strftime('%H:%M:%S'),
                'action': 'checkout',
                'confidence': f'{best_score:.2f}',
                'employee': emp_info,
                'work_hours': work_hours_str,
                'work_hours_float': existing.work_hours,
                'early_checkout': existing.early_checkout,
                'early_checkout_minutes': early_minutes,
            }
            return result
        else:
            return {
                'success': True,
                'name': employee.name,
                'time': 'الدوام مكتمل',
                'action': 'done',
                'confidence': f'{best_score:.2f}',
                'employee': emp_info,
            }

    # تسجيل حضور جديد
    earliest_time = time(settings['earliest_hour'], settings['earliest_minute'])
    start_time = time(settings['start_hour'], settings['start_minute'])

    if current_time < earliest_time:
        return {
            'success': False,
            'message': f'لم يحن وقت تسجيل الحضور بعد! يمكنك تسجيل الحضور بدءاً من الساعة {earliest_time.strftime("%H:%M")}'
        }

    status = 'present'
    late_mins = 0
    allowed_time = (datetime.combine(today, start_time) + timedelta(minutes=settings['grace_period'])).time()
    if current_time > allowed_time:
        status = 'late'
        late_mins = _calculate_late_minutes(current_time, start_time, settings['grace_period'])

    # فحص إجازة ساعية
    hourly_leave = Leave.query.filter(
        Leave.employee_id == employee.id,
        Leave.start_date <= today,
        Leave.end_date >= today,
        Leave.status == 'approved',
        Leave.leave_type == 'hourly'
    ).first()

    notes = ''
    if hourly_leave:
        leave_start = hourly_leave.start_time.strftime('%H:%M') if hourly_leave.start_time else ''
        leave_end = hourly_leave.end_time.strftime('%H:%M') if hourly_leave.end_time else ''
        notes = f'إجازة ساعية: {leave_start} - {leave_end}'

    new_attendance = Attendance(
        employee_id=employee.id, date=today,
        time_in=current_time, status=status,
        late_minutes=late_mins,
        notes=notes if notes else None
    )
    db.session.add(new_attendance)
    db.session.commit()

    action = 'checkin'
    if status == 'late':
        action = 'late'

    result = {
        'success': True,
        'name': employee.name,
        'time': now.strftime('%H:%M:%S'),
        'action': action,
        'status': status,
        'confidence': f'{best_score:.2f}',
        'employee': emp_info,
        'late_minutes': late_mins,
    }

    # إضافة معلومات الإجازة الساعية
    if hourly_leave:
        result['hourly_leave'] = {
            'start': hourly_leave.start_time.strftime('%H:%M') if hourly_leave.start_time else None,
            'end': hourly_leave.end_time.strftime('%H:%M') if hourly_leave.end_time else None,
        }

    return result


def register_leave_out(employee, emp_info, best_score):
    """
    تسجيل خروج إجازة ساعية
    """
    now = datetime.now()
    today = now.date()
    current_time = now.time()

    # فحص إجازة ساعية معتمدة
    hourly_leave = Leave.query.filter(
        Leave.employee_id == employee.id,
        Leave.start_date <= today,
        Leave.end_date >= today,
        Leave.status == 'approved',
        Leave.leave_type == 'hourly'
    ).first()

    if not hourly_leave:
        return {
            'success': False,
            'message': 'لا يوجد إجازة ساعية معتمدة لك اليوم'
        }

    existing = Attendance.query.filter_by(employee_id=employee.id, date=today).first()
    if not existing:
        return {
            'success': False,
            'message': 'يجب تسجيل الحضور أولاً قبل تسجيل خروج إجازة'
        }

    if existing.leave_out is not None:
        return {
            'success': False,
            'message': 'لقد سجّلت خروج إجازة بالفعل'
        }

    if existing.time_out is not None:
        return {
            'success': False,
            'message': 'لقد سجّلت انصراف بالفعل'
        }

    existing.leave_out = current_time
    db.session.commit()

    return {
        'success': True,
        'name': employee.name,
        'time': now.strftime('%H:%M:%S'),
        'action': 'leave_out',
        'confidence': f'{best_score:.2f}',
        'employee': emp_info,
        'leave_end': hourly_leave.end_time.strftime('%H:%M') if hourly_leave.end_time else '',
    }


def register_leave_in(employee, emp_info, best_score):
    """
    تسجيل رجوع من إجازة ساعية
    """
    now = datetime.now()
    today = now.date()
    current_time = now.time()

    existing = Attendance.query.filter_by(employee_id=employee.id, date=today).first()
    if not existing:
        return {
            'success': False,
            'message': 'يجب تسجيل الحضور أولاً'
        }

    if existing.leave_out is None:
        return {
            'success': False,
            'message': 'لم تسجّل خروج إجازة بعد'
        }

    if existing.leave_in is not None:
        return {
            'success': False,
            'message': 'لقد سجّلت رجوع من الإجازة بالفعل'
        }

    if existing.time_out is not None:
        return {
            'success': False,
            'message': 'لقد سجّلت انصراف بالفعل'
        }

    existing.leave_in = current_time

    # حساب مدة الإجازة
    leave_duration = datetime.combine(today, current_time) - datetime.combine(today, existing.leave_out)
    leave_minutes = int(leave_duration.total_seconds() / 60)
    leave_hours = leave_minutes // 60
    leave_mins = leave_minutes % 60

    # فحص رجوع متأخر
    hourly_leave = Leave.query.filter(
        Leave.employee_id == employee.id,
        Leave.start_date <= today,
        Leave.end_date >= today,
        Leave.status == 'approved',
        Leave.leave_type == 'hourly'
    ).first()

    late_return = False
    if hourly_leave and hourly_leave.end_time:
        if current_time > hourly_leave.end_time:
            late_minutes = int((datetime.combine(today, current_time) - datetime.combine(today, hourly_leave.end_time)).total_seconds() / 60)
            late_return = True
            existing.notes = (existing.notes or '') + f' | رجوع متأخر {late_minutes} دقيقة'

    db.session.commit()

    result = {
        'success': True,
        'name': employee.name,
        'time': now.strftime('%H:%M:%S'),
        'action': 'leave_in_late' if late_return else 'leave_in',
        'confidence': f'{best_score:.2f}',
        'employee': emp_info,
        'leave_duration': f'{leave_hours}س {leave_mins}د',
    }
    if late_return:
        result['message'] = 'رجعت متأخراً عن وقت الإجازة المحدد!'

    return result
