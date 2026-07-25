from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import date, datetime
from instance.models import db, Holiday
from utils.helpers import log_action, login_required
from utils.csrf import validate_csrf_token

holidays_bp = Blueprint('holidays', __name__)

# خريطة أنواع العطل
HOLIDAY_TYPES = {
    'national': 'وطنية',
    'religious': 'دينية',
    'government': 'حكومية',
}




@holidays_bp.route('/holidays', endpoint='holidays')
@login_required()
def holidays():
    year = request.args.get('year', date.today().year, type=int)

    # جلب عطل السنة المحددة + العطل المتكررة
    all_holidays = Holiday.query.filter(
        db.or_(
            db.extract('year', Holiday.date) == year,
            Holiday.is_recurring == True
        )
    ).order_by(Holiday.date).all()

    # إضافة display_date للعطل المتكررة (لعرض التاريخ بسنة العرض الحالية)
    for h in all_holidays:
        if h.is_recurring:
            h.display_date = h.date.replace(year=year)
        else:
            h.display_date = h.date

    # إحصائيات - نستخدم display_date للتصنيف (عطل قادمة/ماضية)
    today = date.today()
    upcoming = [h for h in all_holidays if h.display_date >= today]
    past = [h for h in all_holidays if h.display_date < today]
    religious_count = sum(1 for h in all_holidays if h.holiday_type == 'religious')

    return render_template('holidays.html',
        holidays=all_holidays,
        year=year,
        upcoming=upcoming,
        past=past,
        religious_count=religious_count,
        holiday_types=HOLIDAY_TYPES,
        today=today
    )


@holidays_bp.route('/holidays/add', methods=['GET', 'POST'], endpoint='holiday_add')
@login_required()
def holiday_add():
    if request.method == 'POST':
        if not validate_csrf_token(request.form.get('csrf_token')):
            flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
            return redirect(request.url)

        name = request.form.get('name', '').strip()
        date_str = request.form.get('date', '')
        holiday_type = request.form.get('holiday_type', 'national')
        is_recurring = request.form.get('is_recurring') == 'on'
        notes = request.form.get('notes', '').strip()

        if not name or not date_str:
            flash('يرجى ملء اسم العطلة والتاريخ', 'danger')
            return redirect(request.url)

        try:
            holiday_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('تاريخ غير صالح', 'danger')
            return redirect(request.url)

        # فحص هل العطلة موجودة بنفس التاريخ
        existing = Holiday.query.filter_by(date=holiday_date, name=name).first()
        if existing:
            flash(f'العطلة "{name}" موجودة بالفعل في هذا التاريخ', 'danger')
            return redirect(url_for('holidays.holiday_add'))

        holiday = Holiday(
            name=name,
            date=holiday_date,
            holiday_type=holiday_type,
            is_recurring=is_recurring,
            notes=notes or None
        )
        db.session.add(holiday)
        db.session.commit()

        log_action('create', 'holiday', holiday.id, f'إضافة عطلة: {name} ({date_str})')
        flash(f'تم إضافة العطلة "{name}" بنجاح', 'success')
        return redirect(url_for('holidays.holidays'))

    return render_template('holiday_add.html', holiday_types=HOLIDAY_TYPES)


@holidays_bp.route('/holidays/edit/<int:id>', methods=['GET', 'POST'], endpoint='holiday_edit')
@login_required()
def holiday_edit(id):
    """تعديل بيانات عطلة رسمية"""
    holiday = Holiday.query.get_or_404(id)

    if request.method == 'POST':
        if not validate_csrf_token(request.form.get('csrf_token')):
            flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
            return redirect(request.url)

        name = request.form.get('name', '').strip()
        date_str = request.form.get('date', '')
        holiday_type = request.form.get('holiday_type', 'national')
        is_recurring = request.form.get('is_recurring') == 'on'
        notes = request.form.get('notes', '').strip()

        if not name or not date_str:
            flash('يرجى ملء اسم العطلة والتاريخ', 'danger')
            return redirect(request.url)

        try:
            holiday_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('تاريخ غير صالح', 'danger')
            return redirect(request.url)

        # فحص هل العطلة موجودة بنفس التاريخ والاسم (باستثناء العطلة الحالية)
        existing = Holiday.query.filter_by(date=holiday_date, name=name).first()
        if existing and existing.id != id:
            flash(f'العطلة "{name}" موجودة بالفعل في هذا التاريخ', 'danger')
            return redirect(request.url)

        # تحديث بيانات العطلة
        holiday.name = name
        holiday.date = holiday_date
        holiday.holiday_type = holiday_type
        holiday.is_recurring = is_recurring
        holiday.notes = notes or None

        db.session.commit()

        log_action('update', 'holiday', holiday.id, f'تعديل عطلة: {name} ({date_str})')
        flash(f'تم تعديل العطلة "{name}" بنجاح', 'success')
        return redirect(url_for('holidays.holidays'))

    return render_template('holiday_edit.html', holiday=holiday, holiday_types=HOLIDAY_TYPES)


@holidays_bp.route('/holidays/delete/<int:id>', methods=['POST'], endpoint='holiday_delete')
@login_required()
def holiday_delete(id):
    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
        return redirect(url_for('holidays.holidays'))

    holiday = Holiday.query.get_or_404(id)
    db.session.delete(holiday)
    db.session.commit()

    log_action('delete', 'holiday', id, f'حذف عطلة: {holiday.name}')
    flash(f'تم حذف العطلة "{holiday.name}" بنجاح', 'success')
    return redirect(url_for('holidays.holidays'))



