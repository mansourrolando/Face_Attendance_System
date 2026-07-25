from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, flash
from datetime import datetime, date, time, timedelta
import cv2
import numpy as np
import base64
from instance.models import db, Employee, Attendance, Leave, Holiday
from utils.face_utils import embedding_model
from services.attendance_service import (
    verify_face_from_image, register_checkin,
    register_leave_out, register_leave_in,
    _get_work_time_settings
)
from utils.helpers import get_setting, login_required, log_action
from utils.absence_utils import mark_absent_employees, process_forgot_checkouts, auto_end_workday
try:
    from utils.screen_detection import detect_screen as screen_detect_fn
    SCREEN_DETECT_AVAILABLE = True
except ImportError:
    SCREEN_DETECT_AVAILABLE = False
from config import *

attendance_bp = Blueprint('attendance', __name__)


@attendance_bp.route('/attendance', endpoint='attendance_page')
@login_required()
def attendance_page():
    # إنهاء يوم العمل تلقائياً لو تعدى وقت الانصراف
    auto_end_workday()

    recent_logs = Attendance.query.filter_by(date=date.today()).order_by(
        Attendance.time_in.desc()
    ).limit(20).all()

    # جلب عدد الموظفين النشطين الذين لم يسجّلوا حضور اليوم
    active_employees = Employee.query.filter_by(status='active').all()
    present_ids = set()
    for log in recent_logs:
        if log.employee_id:
            present_ids.add(log.employee_id)
    all_today = Attendance.query.filter_by(date=date.today()).all()
    for r in all_today:
        present_ids.add(r.employee_id)

    absent_count = sum(1 for e in active_employees if e.id not in present_ids)

    return render_template('attendance.html', recent_logs=recent_logs, absent_count=absent_count)


@attendance_bp.route('/mark_absent', methods=['POST'], endpoint='mark_absent')
@login_required(api=True)
def mark_absent():
    """تسجيل غياب الموظفين الذين لم يسجّلوا حضور ليوم معين"""
    data = request.get_json() or {}
    target_date_str = data.get('date')

    if target_date_str:
        try:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
        except:
            return jsonify({'success': False, 'message': 'تاريخ غير صالح'})
    else:
        target_date = date.today() - timedelta(days=1)

    result = mark_absent_employees(target_date)

    log_action('update', 'attendance', description=f'تسجيل غياب تلقائي لتاريخ {target_date}: {result["marked"]} غائب')

    return jsonify({
        'success': True,
        'message': f'تم تسجيل غياب {result["marked"]} موظف لتاريخ {target_date}',
        'result': result
    })


@attendance_bp.route('/mark_absent_today', methods=['POST'], endpoint='mark_absent_today')
@login_required()
def mark_absent_today():
    """زر إنهاء يوم العمل - يسجّل انصراف تلقائي لمن نسي + غياب لمن لم يسجّل حضور"""
    today = date.today()

    work_end_setting = get_setting('work_end', WORK_END_TIME)
    try:
        end_hour, end_minute = map(int, work_end_setting.split(':'))
    except:
        end_hour, end_minute = map(int, WORK_END_TIME.split(':'))

    now = datetime.now()
    work_end_time = time(end_hour, end_minute)

    if now.time() < work_end_time:
        flash('لا يمكن تسجيل غياب اليوم قبل انتهاء ساعات العمل!', 'warning')
        return redirect(url_for('attendance.attendance_page'))

    # 1. معالجة من سجّل حضور ولم يسجّل انصراف
    forgot_count = process_forgot_checkouts(today, work_end_setting)

    # 2. تسجيل غياب لمن لم يسجّل حضور أبداً
    active_employees = Employee.query.filter_by(status='active').all()
    today_records = Attendance.query.filter_by(date=today).all()
    present_ids = {r.employee_id for r in today_records}

    marked = 0
    for emp in active_employees:
        if emp.id in present_ids:
            continue
        if emp.hire_date and today < emp.hire_date:
            continue

        on_leave = Leave.query.filter(
            Leave.employee_id == emp.id,
            Leave.start_date <= today,
            Leave.end_date >= today,
            Leave.status == 'approved',
            Leave.leave_type != 'hourly'
        ).first()

        if on_leave:
            attendance = Attendance(
                employee_id=emp.id, date=today, status='leave',
                notes=f'إجازة {on_leave.leave_type}'
            )
            db.session.add(attendance)
        else:
            absence = Attendance(
                employee_id=emp.id, date=today, status='absent',
                absence_type='unjustified', notes='غياب غير مبرر - لم يسجّل حضور'
            )
            db.session.add(absence)
            marked += 1

    from instance.models import Setting
    workday_key = f'workday_ended_{today.isoformat()}'
    already_ended = Setting.query.filter_by(key=workday_key).first()
    if not already_ended:
        ended_flag = Setting(key=workday_key, value=now.strftime('%Y-%m-%d %H:%M:%S'))
        db.session.add(ended_flag)

    db.session.commit()

    log_action('update', 'attendance', description=f'إنهاء يوم العمل: {marked} غائب، {forgot_count} انصراف تلقائي')

    msg_parts = []
    if marked > 0:
        msg_parts.append(f'تسجيل غياب {marked} موظف')
    if forgot_count > 0:
        msg_parts.append(f'انصراف تلقائي لـ {forgot_count} موظف نسوا تسجيل الانصراف')
    if not msg_parts:
        msg_parts.append('جميع الموظفين سجّلوا حضورهم وانصرافهم')

    flash(' | '.join(msg_parts), 'success')
    return redirect(url_for('attendance.attendance_page'))


@attendance_bp.route('/verify_face', methods=['POST'], endpoint='verify_face')
@login_required(api=True)
def verify_face():
    """التحقق من الوجه - صفحة الحضور"""
    if embedding_model is None:
        return jsonify({'success': False, 'message': 'النموذج غير محمل'})

    try:
        data = request.get_json()
        image_data = data['image'].split(',')[1]
        image_bytes = base64.b64decode(image_data)
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # كشف الشاشات
        if SCREEN_DETECT_AVAILABLE:
            try:
                screen_res = screen_detect_fn(img)
                if screen_res.get('is_screen', False):
                    return jsonify({
                        'success': False,
                        'message': 'تم كشف شاشة هاتف/تابلت - احتيال محتمل!',
                        'screen_detected': True,
                        'screen_detail': screen_res.get('message', ''),
                    })
            except Exception:
                pass

        # التحقق من الوجه
        face_ok, face_result = verify_face_from_image(img)
        if not face_ok:
            return jsonify({'success': False, 'message': face_result['message']})

        best_match = face_result['best_match']
        best_score = face_result['best_score']
        emp_info = face_result['emp_info']

        # تسجيل حضور/انصراف
        settings = _get_work_time_settings(best_match)
        result = register_checkin(best_match, emp_info, best_score, settings)

        return jsonify(result)

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@attendance_bp.route('/leave_out', methods=['POST'], endpoint='leave_out')
@login_required(api=True)
def leave_out():
    """تسجيل خروج الموظف لإجازة ساعية"""
    if embedding_model is None:
        return jsonify({'success': False, 'message': 'النموذج غير محمل'})

    try:
        data = request.get_json()
        image_data = data['image'].split(',')[1]
        image_bytes = base64.b64decode(image_data)
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # كشف الشاشات
        if SCREEN_DETECT_AVAILABLE:
            try:
                screen_res = screen_detect_fn(img)
                if screen_res.get('is_screen', False):
                    return jsonify({
                        'success': False,
                        'message': 'تم كشف شاشة هاتف/تابلت - احتيال محتمل!',
                        'screen_detected': True,
                        'screen_detail': screen_res.get('message', ''),
                    })
            except Exception:
                pass

        face_ok, face_result = verify_face_from_image(img)
        if not face_ok:
            return jsonify({'success': False, 'message': face_result['message']})

        best_match = face_result['best_match']
        best_score = face_result['best_score']
        emp_info = face_result['emp_info']

        result = register_leave_out(best_match, emp_info, best_score)
        return jsonify(result)

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@attendance_bp.route('/leave_in', methods=['POST'], endpoint='leave_in')
@login_required(api=True)
def leave_in():
    """تسجيل رجوع الموظف من إجازة ساعية"""
    if embedding_model is None:
        return jsonify({'success': False, 'message': 'النموذج غير محمل'})

    try:
        data = request.get_json()
        image_data = data['image'].split(',')[1]
        image_bytes = base64.b64decode(image_data)
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # كشف الشاشات
        if SCREEN_DETECT_AVAILABLE:
            try:
                screen_res = screen_detect_fn(img)
                if screen_res.get('is_screen', False):
                    return jsonify({
                        'success': False,
                        'message': 'تم كشف شاشة هاتف/تابلت - احتيال محتمل!',
                        'screen_detected': True,
                        'screen_detail': screen_res.get('message', ''),
                    })
            except Exception:
                pass

        face_ok, face_result = verify_face_from_image(img)
        if not face_ok:
            return jsonify({'success': False, 'message': face_result['message']})

        best_match = face_result['best_match']
        best_score = face_result['best_score']
        emp_info = face_result['emp_info']

        result = register_leave_in(best_match, emp_info, best_score)
        return jsonify(result)

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
