from functools import wraps
from flask import session, request, jsonify, redirect, url_for
from instance.models import db, AuditLog, Setting

def login_required(api=False):
    """Decorator للتحقق من تسجيل الدخول وفحص IP المحظورة"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # فحص 1: هل المستخدم مسجّل دخوله؟
            if 'userId' not in session:
                if api:
                    return jsonify({'success': False, 'message': 'غير مصرح'}), 403
                return redirect(url_for('auth.login'))
            
            # 🛡️ فحص 2: هل IP محظور؟ (Continuous Authorization)
            from instance.models import BlockedIP
            client_ip = request.remote_addr
            blocked = BlockedIP.query.filter_by(ip_address=client_ip).first()
            if blocked:
                # IP محظور! طرد المستخدم فوراً
                session.clear()  # مسح الجلسة
                if api:
                    return jsonify({'success': False, 'message': 'تم حظر هذا العنوان'}), 403
                from flask import flash
                flash(f'🚫 تم حظر هذا العنوان (IP) بسبب: {blocked.reason or "نشاط مشبوه"}', 'danger')
                return redirect(url_for('auth.login'))
            
            # المستخدم مسجّل و IP غير محظور ← نفّذ الدالة
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def log_action(action, entity_type=None, entity_id=None, description=None,
               success=True, ip_address=None, user_agent=None, user_id=None, user_name=None):
    """تسجيل إجراء في سجل النشاط.

    المعاملات الجديدة (للمراقبة الأمنية):
      - success: True للإجراء الناجح، False للفاشل (مثل محاولة دخول فاشلة)
      - ip_address: عنوان IP للمستخدم (إذا None يُجلب تلقائياً من request)
      - user_agent: معلومات المتصفح (إذا None يُجلب تلقائياً من request)
      - user_id / user_name: لتسجيل محاولات بأسماء مستخدمين لم يتم التحقق منهم
                             (مثل login_failed لكلمة مرور خاطئة)
    """
    try:
        # إذا لم تُمرر قيم صريحة، استخدم الجلسة الحالية
        if user_id is None:
            user_id = session.get('userId')
        if user_name is None:
            user_name = session.get('user_name', 'مجهول')
        # جلب IP و User-Agent تلقائياً من الطلب الحالي إذا لم تُمرر صراحةً
        if ip_address is None:
            try:
                ip_address = request.remote_addr
            except RuntimeError:
                ip_address = None  # قد يفشل خارج سياق الطلب
        if user_agent is None:
            try:
                user_agent = (request.headers.get('User-Agent') or '')[:255]
            except RuntimeError:
                user_agent = None

        log = AuditLog(
            user_id=user_id,
            user_name=user_name,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description,
            ip_address=ip_address,
            user_agent=user_agent,
            success=success
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        print(f'[ERROR] Audit log failed: {e}')


def get_setting(key, default=None):
    """دالة مساعدة لجلب قيمة إعداد معين من قاعدة البيانات"""
    setting = Setting.query.filter_by(key=key).first()
    if setting:
        return setting.value
    return default


def _calc_work_hours(time_in, time_out):
    """حساب مدة العمل بين وقت الحضور والانصراف"""
    from datetime import datetime, date
    if time_in and time_out:
        dt_in = datetime.combine(date.today(), time_in)
        dt_out = datetime.combine(date.today(), time_out)
        diff = dt_out - dt_in
        total_seconds = int(diff.total_seconds())
        if total_seconds < 0:
            return '-'
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f'{hours}س {minutes}د'
    return '-'


def _calc_leave_hours(leave_out, leave_in):
    """حساب مدة الإجازة الساعية بين وقت الخروج والرجوع"""
    from datetime import datetime, date
    if leave_out and leave_in:
        dt_out = datetime.combine(date.today(), leave_out)
        dt_in = datetime.combine(date.today(), leave_in)
        diff = dt_in - dt_out
        total_seconds = int(diff.total_seconds())
        if total_seconds < 0:
            return '-'
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f'{hours}س {minutes}د'
    return '-'


def format_work_hours(hours_float):
    """تحويل ساعات العمل العشرية إلى صيغة نصية (8.5 -> 8س 30د)"""
    if hours_float is None:
        return '-'
    hours = int(hours_float)
    minutes = int(round((hours_float - hours) * 60))
    return f'{hours}س {minutes}د'


def format_minutes(minutes):
    """تحويل الدقائق إلى صيغة نصية (90 -> 1س 30د)"""
    if minutes is None or minutes == 0:
        return '0د'
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f'{hours}س {mins}د'
    return f'{mins}د'
