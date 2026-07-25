from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort
from instance.models import db, AuditLog, BlockedIP
from utils.helpers import login_required, log_action
from utils.csrf import validate_csrf_token
from sqlalchemy import func

audit_bp = Blueprint('audit', __name__)


@audit_bp.route('/audit_log', endpoint='audit_log')
@login_required()
def audit_log():
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # فلترة
    action_filter = request.args.get('action', '')
    entity_filter = request.args.get('entity', '')
    status_filter = request.args.get('status', '')
    ip_filter = request.args.get('ip', '').strip()

    query = AuditLog.query
    if action_filter:
        query = query.filter_by(action=action_filter)
    if entity_filter:
        query = query.filter_by(entity_type=entity_filter)
    if status_filter == 'success':
        query = query.filter_by(success=True)
    elif status_filter == 'failed':
        query = query.filter_by(success=False)
    if ip_filter:
        query = query.filter(AuditLog.ip_address.like(f'%{ip_filter}%'))

    logs = query.order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)

    # إحصائيات سريعة للأمان
    total_failed = AuditLog.query.filter_by(success=False).count()
    distinct_ips_failed = AuditLog.query.filter(
        AuditLog.success == False,
        AuditLog.ip_address.isnot(None)
    ).distinct(AuditLog.ip_address).count()

    # جلب قائمة IPs المحظورة لعرضها في الصفحة
    blocked_ips = BlockedIP.query.order_by(BlockedIP.blocked_at.desc()).all()

    return render_template('audit_log.html',
                           logs=logs,
                           action_filter=action_filter,
                           entity_filter=entity_filter,
                           status_filter=status_filter,
                           ip_filter=ip_filter,
                           total_failed=total_failed,
                           distinct_ips_failed=distinct_ips_failed,
                           blocked_ips=blocked_ips)


# ==========================================
# إدارة حظر IPs (IP Blocking Management)
# ==========================================

@audit_bp.route('/block_ip', methods=['POST'], endpoint='block_ip')
@login_required()
def block_ip():
    """حظر IP يدوياً من قبل المدير"""
    # فحص CSRF
    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('رمز الأمان غير صالح', 'danger')
        return redirect(url_for('audit.audit_log'))
    
    ip = request.form.get('ip_address', '').strip()
    reason = request.form.get('reason', 'نشاط مشبوه - محاولات دخول فاشلة متكررة').strip()
    
    if not ip:
        flash('لم يتم تحديد IP للحظر', 'danger')
        return redirect(url_for('audit.audit_log'))
    
    # فحص هل محظور مسبقاً
    existing = BlockedIP.query.filter_by(ip_address=ip).first()
    if existing:
        flash(f'IP {ip} محظور مسبقاً', 'warning')
        return redirect(url_for('audit.audit_log'))
    
    # إنشاء الحظر
    blocked = BlockedIP(
        ip_address=ip,
        reason=reason,
        blocked_by=session.get('userId')
    )
    db.session.add(blocked)
    db.session.commit()
    
    # تسجيل الحظر في audit_log
    log_action('block_ip',
               entity_type='ip',
               description=f'حظر IP: {ip} - السبب: {reason}')
    
    flash(f'✅ تم حظر IP: {ip}', 'success')
    return redirect(url_for('audit.audit_log'))


@audit_bp.route('/unblock_ip/<int:blocked_id>', methods=['POST'], endpoint='unblock_ip')
@login_required()
def unblock_ip(blocked_id):
    """فك حظر IP"""
    # فحص CSRF
    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('رمز الأمان غير صالح', 'danger')
        return redirect(url_for('audit.audit_log'))
    
    blocked = BlockedIP.query.get_or_404(blocked_id)
    ip = blocked.ip_address
    db.session.delete(blocked)
    db.session.commit()
    
    # تسجيل فك الحظر في audit_log
    log_action('unblock_ip',
               entity_type='ip',
               description=f'إلغاء حظر IP: {ip}')
    
    flash(f'✅ تم إلغاء حظر IP: {ip}', 'success')
    return redirect(url_for('audit.audit_log'))