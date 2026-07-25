from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, date
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
from utils.helpers import get_setting
from utils.absence_utils import auto_end_workday
try:
    from utils.screen_detection import detect_screen as screen_detect_fn
    SCREEN_DETECT_AVAILABLE = True
except ImportError:
    SCREEN_DETECT_AVAILABLE = False
from config import *

try:
    KIOSK_PIN
except NameError:
    KIOSK_PIN = '1234'
try:
    KIOSK_WELCOME_DURATION
except NameError:
    KIOSK_WELCOME_DURATION = 5

kiosk_bp = Blueprint('kiosk', __name__)


def _decode_base64_image(image_data_str):
    """فك تشفير صورة base64 إلى مصفوفة OpenCV"""
    image_bytes = base64.b64decode(image_data_str)
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    return img


@kiosk_bp.route('/kiosk', endpoint='kiosk_mode')
def kiosk_mode():
    """صفحة الكشك - لا تحتاج تسجيل دخول"""
    # إنهاء يوم العمل تلقائياً لو تعدى وقت الانصراف التلقائي
    auto_end_workday()

    welcome_duration = int(get_setting('kiosk_welcome_duration', str(KIOSK_WELCOME_DURATION)))
    return render_template('kiosk.html',
                           kiosk_welcome_duration=welcome_duration)


@kiosk_bp.route('/kiosk_verify', methods=['POST'], endpoint='kiosk_verify')
def kiosk_verify():
    """التحقق من الوجه من الكشك - بدون الحاجة لـ session"""
    if embedding_model is None:
        return jsonify({'success': False, 'message': 'النموذج غير محمل'})

    data = request.get_json()
    action_type = data.get('action_type', 'auto')  # auto, leave_out, leave_in

    try:
        # 1. فك تشفير الصورة
        image_data = data['image'].split(',')[1]
        img = _decode_base64_image(image_data)

        if img is None:
            return jsonify({'success': False, 'message': 'فشل في قراءة الصورة'})

        # 2. كشف الشاشات (حماية ضد الاحتيال بالهاتف)
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
            except Exception as e:
                print(f'[WARN] فشل كشف الشاشة في kiosk_verify: {e}')

        # 3. التحقق من الوجه
        face_ok, face_result = verify_face_from_image(img)
        if not face_ok:
            return jsonify({'success': False, 'message': face_result['message']})

        best_match = face_result['best_match']
        best_score = face_result['best_score']
        emp_info = face_result['emp_info']

        # 4. تنفيذ الإجراء المناسب
        if action_type == 'leave_out':
            result = register_leave_out(best_match, emp_info, best_score)
        elif action_type == 'leave_in':
            result = register_leave_in(best_match, emp_info, best_score)
        else:  # auto - حضور/انصراف
            settings = _get_work_time_settings(best_match)
            result = register_checkin(best_match, emp_info, best_score, settings)

        return jsonify(result)

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@kiosk_bp.route('/kiosk_exit', methods=['POST'], endpoint='kiosk_exit')
def kiosk_exit():
    """تعطيل وضع الكشك - يتطلب PIN"""
    pin = request.form.get('pin', '')
    kiosk_pin = get_setting('kiosk_pin', KIOSK_PIN)
    if pin == kiosk_pin:
        return redirect(url_for('auth.login'))
    else:
        flash('رمز PIN غير صحيح', 'danger')
        return redirect(url_for('kiosk.kiosk_mode'))


@kiosk_bp.route('/kiosk_recent', endpoint='kiosk_recent')
def kiosk_recent():
    """آخر سجلات الحضور اليوم للكشك"""
    status_map_action = {'present': 'checkin', 'late': 'late', 'leave': 'leave'}
    records = Attendance.query.filter_by(date=date.today()).order_by(
        Attendance.time_in.desc()
    ).limit(10).all()

    logs = []
    for r in records:
        action = status_map_action.get(r.status, 'checkin')
        if r.time_out:
            action = 'checkout'
        logs.append({
            'name': r.employee.name if r.employee else '-',
            'time': r.time_in.strftime('%H:%M') if r.time_in else '-',
            'action': action
        })

    return jsonify({'logs': logs})