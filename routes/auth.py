from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime
from instance.models import db, User
from utils.rate_limit import login_attempts, username_attempts
from utils.helpers import log_action, get_setting
from utils.csrf import validate_csrf_token
from config import *

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/', endpoint='index')
def index():
    if 'userId' in session:
        return redirect(url_for('dashboard.dashboard'))
    return redirect(url_for('auth.login'))

# ==========================================================================================
# Login / Logout
# ==========================================================================================
@auth_bp.route('/login', methods=['GET', 'POST'], endpoint='login')
def login():
    from instance.models import BlockedIP
    
    # 🛡️ طبقة 0: فحص IP المحظورة يدوياً
    client_ip = request.remote_addr
    blocked = BlockedIP.query.filter_by(ip_address=client_ip).first()
    if blocked:
        flash(f'🚫 تم حظر هذا العنوان (IP) بسبب: {blocked.reason or "نشاط مشبوه"}', 'danger')
        return render_template('login.html'), 403
    
    if request.method == 'POST':
        # ===== طبقة 1: CSRF Protection =====
        if not validate_csrf_token(request.form.get('csrf_token')):
            flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
            return redirect(request.url)
        
        client_key = request.remote_addr
        username = request.form.get('userId')  # ✅ نقلناه فوق
        
        # جلب إعدادات Rate Limiting
        max_attempts = int(get_setting('max_login_attempts', str(MAX_LOGIN_ATTEMPTS)))
        lockout_minutes = int(get_setting('login_lockout_minutes', str(LOGIN_LOCKOUT_MINUTES)))
        
        # ===== طبقة 2: Rate Limiting (IP) =====
        if client_key in login_attempts:
            attempt_data = login_attempts[client_key]
            if attempt_data['count'] >= max_attempts:
                elapsed = (datetime.now() - attempt_data['last_attempt']).total_seconds() / 60
                if elapsed < lockout_minutes:
                    remaining = int(lockout_minutes - elapsed)
                    flash(f'تم تجاوز عدد المحاولات المسموحة. حاول مرة أخرى بعد {remaining} دقيقة.', 'danger')
                    return render_template('login.html')
                else:
                    del login_attempts[client_key]
        
        # ===== طبقة 2.5: Rate Limiting (username - يحمي من VPN) =====
        if username and username in username_attempts:
            data = username_attempts[username]
            time_diff = datetime.now() - data['window_start']
            
            if time_diff.total_seconds() > 3600:  # ساعة = 3600 ثانية
                del username_attempts[username]
            elif data['count'] >= 20:
                flash('⚠️ نشاط مشبوه على هذا الحساب. تم الحظر لمدة ساعة.', 'danger')
                return render_template('login.html')
        
        password = request.form.get('userPassword')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            session['userId'] = user.id
            session['username'] = user.username
            session['user_name'] = user.name
            
            if client_key in login_attempts:
                del login_attempts[client_key]
            
            # ✅ حذف username_attempts عند النجاح
            if username in username_attempts:
                del username_attempts[username]
            
            user.last_login = datetime.now()
            db.session.commit()
            
            # ===== طبقة 3: Audit Log (نجاح) =====
            log_action('login',
                       description=f'تسجيل دخول ناجح: {username}',
                       success=True,
                       user_id=user.id,
                       user_name=user.name)
            
            flash('تم تسجيل الدخول بنجاح', 'success')
            
            if user.must_change_password:
                flash('يجب تغيير كلمة المرور الافتراضية قبل المتابعة!', 'warning')
                return redirect(url_for('settings.settings'))
            
            return redirect(url_for('dashboard.dashboard'))
        else:
            # ❌ فشل! زيادة عدّاد المحاولات الفاشلة (IP)
            if client_key not in login_attempts:
                login_attempts[client_key] = {'count': 0, 'last_attempt': datetime.now()}
            login_attempts[client_key]['count'] += 1
            login_attempts[client_key]['last_attempt'] = datetime.now()
            
            # ✅ زيادة عدّاد username
            if username:
                if username not in username_attempts:
                    username_attempts[username] = {'count': 0, 'window_start': datetime.now()}
                username_attempts[username]['count'] += 1
            
            # ===== طبقة 3: Audit Log (فشل) =====
            if user:
                log_action('login_failed',
                           description=f'محاولة دخول فاشلة (كلمة مرور خاطئة): {username}',
                           success=False,
                           user_id=user.id,
                           user_name=user.name)
            else:
                log_action('login_failed',
                           description=f'محاولة دخول فاشلة (مستخدم غير موجود): {username}',
                           success=False,
                           user_id=None,
                           user_name=username or 'غير محدد')
            
            remaining_attempts = max_attempts - login_attempts[client_key]['count']
            if remaining_attempts > 0:
                flash(f'اسم المستخدم أو كلمة المرور غير صحيحة. محاولات متبقية: {remaining_attempts}', 'danger')
            else:
                flash(f'تم تجاوز عدد المحاولات المسموحة. حاول مرة أخرى بعد {lockout_minutes} دقائق.', 'danger')
    
    return render_template('login.html')



@auth_bp.route('/logout', endpoint='logout')
def logout():
    log_action('logout', description='تسجيل خروج')
    session.clear()
    flash('تم تسجيل الخروج بنجاح', 'success')
    return redirect(url_for('auth.login'))
