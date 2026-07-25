"""
النسخ الاحتياطي والاستعادة - نسخ قاعدة البيانات واستعادتها
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file
from datetime import datetime, date
import os
import shutil
import glob
from instance.models import db
from utils.helpers import log_action, login_required
from utils.csrf import validate_csrf_token

backup_bp = Blueprint('backup', __name__)

# مجلد النسخ الاحتياطية
BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backups')


@backup_bp.route('/backup', endpoint='backup_page')
@login_required()
def backup_page():
    """صفحة النسخ الاحتياطي"""
    # إنشاء مجلد النسخ الاحتياطية إذا لم يكن موجوداً
    os.makedirs(BACKUP_DIR, exist_ok=True)

    # جلب قائمة النسخ الاحتياطية الموجودة
    backups = []
    for f in sorted(glob.glob(os.path.join(BACKUP_DIR, '*.db')), reverse=True):
        stat = os.stat(f)
        filename = os.path.basename(f)
        # تحليل اسم الملف: attendance_system_20260101_120000.db
        try:
            parts = filename.replace('attendance_system_', '').replace('.db', '').split('_')
            backup_date = f'{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:8]}'
            backup_time = f'{parts[1][:2]}:{parts[1][2:4]}:{parts[1][4:6]}' if len(parts) > 1 else ''
        except:
            backup_date = ''
            backup_time = ''

        backups.append({
            'filename': filename,
            'date': backup_date,
            'time': backup_time,
            'size': round(stat.st_size / 1024, 1),  # KB
            'created': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
        })

    return render_template('backup.html', backups=backups)


@backup_bp.route('/backup/create', methods=['POST'], endpoint='backup_create')
@login_required()
def backup_create():
    """إنشاء نسخة احتياطية من قاعدة البيانات"""
    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
        return redirect(url_for('backup.backup_page'))

    os.makedirs(BACKUP_DIR, exist_ok=True)

    # مسار قاعدة البيانات الحالية
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'instance', 'attendance_system.db')

    if not os.path.exists(db_path):
        flash('قاعدة البيانات غير موجودة!', 'danger')
        return redirect(url_for('backup.backup_page'))

    # اسم ملف النسخة الاحتياطية
    now = datetime.now()
    backup_filename = f'attendance_system_{now.strftime("%Y%m%d_%H%M%S")}.db'
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    try:
        # نسخ قاعدة البيانات (مع التأكد من عدم وجود اتصال نشط)
        shutil.copy2(db_path, backup_path)

        # حفظ معلومات النسخة
        info_filename = backup_filename.replace('.db', '.info')
        info_path = os.path.join(BACKUP_DIR, info_filename)
        with open(info_path, 'w', encoding='utf-8') as f:
            f.write(f'date={now.strftime("%Y-%m-%d %H:%M:%S")}\n')
            f.write(f'user={session.get("user_name", "مجهول")}\n')
            f.write(f'size={os.path.getsize(backup_path)}\n')

        log_action('create', 'backup', description=f'إنشاء نسخة احتياطية: {backup_filename}')
        flash(f'تم إنشاء النسخة الاحتياطية بنجاح: {backup_filename}', 'success')
    except Exception as e:
        flash(f'حدث خطأ أثناء إنشاء النسخة الاحتياطية: {str(e)}', 'danger')

    return redirect(url_for('backup.backup_page'))


@backup_bp.route('/backup/download/<filename>', endpoint='backup_download')
@login_required()
def backup_download(filename):
    """تحميل نسخة احتياطية"""
    # أمان: التأكد من اسم الملف
    if '..' in filename or '/' in filename or '\\' in filename:
        flash('اسم ملف غير صالح', 'danger')
        return redirect(url_for('backup.backup_page'))

    backup_path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(backup_path):
        flash('النسخة الاحتياطية غير موجودة', 'danger')
        return redirect(url_for('backup.backup_page'))

    log_action('read', 'backup', description=f'تحميل نسخة احتياطية: {filename}')
    return send_file(backup_path,
                    mimetype='application/x-sqlite3',
                    as_attachment=True,
                    download_name=filename)


@backup_bp.route('/backup/restore/<filename>', methods=['POST'], endpoint='backup_restore')
@login_required()
def backup_restore(filename):
    """استعادة نسخة احتياطية"""
    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
        return redirect(url_for('backup.backup_page'))

    # أمان: التأكد من اسم الملف
    if '..' in filename or '/' in filename or '\\' in filename:
        flash('اسم ملف غير صالح', 'danger')
        return redirect(url_for('backup.backup_page'))

    backup_path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(backup_path):
        flash('النسخة الاحتياطية غير موجودة', 'danger')
        return redirect(url_for('backup.backup_page'))

    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'instance', 'attendance_system.db')

    try:
        # إنشاء نسخة احتياطية للقاعدة الحالية قبل الاستعادة
        now = datetime.now()
        pre_restore_filename = f'attendance_system_pre_restore_{now.strftime("%Y%m%d_%H%M%S")}.db'
        pre_restore_path = os.path.join(BACKUP_DIR, pre_restore_filename)

        if os.path.exists(db_path):
            shutil.copy2(db_path, pre_restore_path)

        # استعادة النسخة الاحتياطية
        shutil.copy2(backup_path, db_path)

        log_action('update', 'backup', description=f'استعادة نسخة احتياطية: {filename} (نسخة قبل الاستعادة: {pre_restore_filename})')
        flash(f'تم استعادة النسخة الاحتياطية بنجاح! تم حفظ نسخة من القاعدة الحالية باسم {pre_restore_filename}', 'success')
        flash('يرجى إعادة تشغيل التطبيق لتفعيل التغييرات', 'warning')
    except Exception as e:
        flash(f'حدث خطأ أثناء استعادة النسخة الاحتياطية: {str(e)}', 'danger')

    return redirect(url_for('backup.backup_page'))


@backup_bp.route('/backup/delete/<filename>', methods=['POST'], endpoint='backup_delete')
@login_required()
def backup_delete(filename):
    """حذف نسخة احتياطية"""
    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
        return redirect(url_for('backup.backup_page'))

    # أمان: التأكد من اسم الملف
    if '..' in filename or '/' in filename or '\\' in filename:
        flash('اسم ملف غير صالح', 'danger')
        return redirect(url_for('backup.backup_page'))

    backup_path = os.path.join(BACKUP_DIR, filename)
    if os.path.exists(backup_path):
        os.remove(backup_path)
        # حذف ملف المعلومات أيضاً
        info_path = backup_path.replace('.db', '.info')
        if os.path.exists(info_path):
            os.remove(info_path)
        log_action('delete', 'backup', description=f'حذف نسخة احتياطية: {filename}')
        flash(f'تم حذف النسخة الاحتياطية: {filename}', 'success')
    else:
        flash('النسخة الاحتياطية غير موجودة', 'danger')

    return redirect(url_for('backup.backup_page'))
