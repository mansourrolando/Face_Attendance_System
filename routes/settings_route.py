from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from instance.models import db, User, Setting
from utils.helpers import log_action, get_setting, login_required
from utils.csrf import validate_csrf_token
from config import *

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/settings', methods=['GET', 'POST'], endpoint='settings')
@login_required()
def settings():
    if request.method == 'POST':
        if not validate_csrf_token(request.form.get('csrf_token')):
            flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
            return redirect(request.url)
        # حفظ الإعدادات
        setting_keys = [
            # إعدادات الدوام
            'work_start', 'work_end', 'grace_period', 'attendance_earliest_time',
            # أيام العطلة الأسبوعية
            'weekend_days',
            # رصيد الإجازات الافتراضي
            'default_annual_leave_balance', 'default_sick_leave_balance',
            # الانصراف التلقائي
            'auto_checkout_enabled', 'auto_checkout_after_hours',
            # تقييد تسجيل الدخول
            'max_login_attempts', 'login_lockout_minutes',
            # التعرف على الوجه
            'registration_images',
            # الكشك
            'kiosk_pin', 'kiosk_welcome_duration',
        ]

        # الحقول اللي هي checkboxes - لما تكون مطفية ما بتبعت قيمة
        checkbox_keys = {'auto_checkout_enabled'}

        for key in setting_keys:
            if key in checkbox_keys:
                # checkbox: موجود في الفورم = مفعّل (true)، غير موجود = معطّل (false)
                value = 'true' if key in request.form else 'false'
            else:
                value = request.form.get(key)
            if value is not None:
                existing = Setting.query.filter_by(key=key).first()
                if existing:
                    existing.value = value
                else:
                    db.session.add(Setting(key=key, value=value))
        db.session.commit()
        log_action('update', 'setting', description='تحديث إعدادات النظام')

        flash('تم حفظ الإعدادات بنجاح', 'success')

    # جلب الإعدادات الحالية
    settings_dict = {}
    for s in Setting.query.all():
        settings_dict[s.key] = s.value

    # جلب بيانات المستخدم الحالي
    current_user = User.query.get(session['userId'])

    return render_template('settings.html', settings=settings_dict, current_user=current_user)


@settings_bp.route('/change_password', methods=['POST'], endpoint='change_password')
@login_required()
def change_password():
    """تغيير كلمة المرور للمستخدم الحالي"""
    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
        return redirect(url_for('settings.settings'))
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    # التحقق من الحقول
    if not current_password or not new_password or not confirm_password:
        flash('يرجى ملء جميع الحقول', 'danger')
        return redirect(url_for('settings.settings'))

    # التحقق من كلمة المرور الحالية
    user = User.query.get(session['userId'])
    if not user or not user.check_password(current_password):
        flash('كلمة المرور الحالية غير صحيح', 'danger')
        return redirect(url_for('settings.settings'))

    # التحقق من طول كلمة المرور الجديدة
    if len(new_password) < 6:
        flash('كلمة المرور الجديدة يجب أن تكون 6 أحرف على الأقل', 'danger')
        return redirect(url_for('settings.settings'))

    # التحقق من تطابق كلمة المرور الجديدة
    if new_password != confirm_password:
        flash('كلمة المرور الجديدة وتأكيدها غير متطابقتين', 'danger')
        return redirect(url_for('settings.settings'))

    # التحقق من أن كلمة المرور الجديدة مختلفة عن الحالية
    if user.check_password(new_password):
        flash('كلمة المرور الجديدة يجب أن تكون مختلفة عن الحالية', 'danger')
        return redirect(url_for('settings.settings'))

    # تغيير كلمة المرور
    user.set_password(new_password)
    user.must_change_password = False  # إزالة إجبار التغيير
    db.session.commit()
    log_action('update', 'user', user.id, 'تغيير كلمة المرور')
    flash('تم تغيير كلمة المرور بنجاح', 'success')
    return redirect(url_for('settings.settings'))