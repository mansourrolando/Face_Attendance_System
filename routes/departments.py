from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from instance.models import db, Department, Employee
from utils.helpers import log_action, login_required
from utils.csrf import validate_csrf_token

departments_bp = Blueprint('departments', __name__)


@departments_bp.route('/departments', endpoint='departments')
@login_required()
def departments():
    department_list = Department.query.all()
    # حساب عدد الموظفين النشطين وغير النشطين لكل قسم
    dept_stats = {}
    for dept in department_list:
        active_count = Employee.query.filter_by(department_id=dept.id, status='active').count()
        inactive_count = Employee.query.filter_by(department_id=dept.id).count() - active_count
        dept_stats[dept.id] = {'active': active_count, 'inactive': inactive_count}
    return render_template('departments.html', departments=department_list, dept_stats=dept_stats)


@departments_bp.route('/departments/<int:id>/employees', endpoint='department_employees')
@login_required()
def department_employees(id):
    department = Department.query.get_or_404(id)
    status_filter = request.args.get('status', 'all')
    if status_filter == 'active':
        employees = Employee.query.filter_by(department_id=id, status='active').order_by(Employee.name).all()
    elif status_filter == 'inactive':
        employees = Employee.query.filter(Employee.department_id == id, Employee.status != 'active').order_by(Employee.name).all()
    else:
        employees = Employee.query.filter_by(department_id=id).order_by(Employee.name).all()

    active_count = Employee.query.filter_by(department_id=id, status='active').count()
    inactive_count = Employee.query.filter_by(department_id=id).count() - active_count

    return render_template(
        'department_employees.html',
        department=department,
        employees=employees,
        active_count=active_count,
        inactive_count=inactive_count,
        status_filter=status_filter
    )

@departments_bp.route('/departments/add', methods=['GET', 'POST'], endpoint='department_add')
@login_required()
def department_add():
    if request.method == 'POST':
        if not validate_csrf_token(request.form.get('csrf_token')):
            flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
            return redirect(request.url)
        
        # طبقة 2: التحقق من التكرار (لا يمكن وجود قسمين بنفس الاسم)
        name = request.form.get('name')
        existing_dept = Department.query.filter_by(name=name).first()
        if existing_dept:
            flash('خطأ: اسم القسم موجود مسبقاً', 'danger')
            return redirect(url_for('departments.department_add'))
        
         # إنشاء القسم
        department = Department(name=name, description=request.form.get('description'))
        db.session.add(department)
        db.session.commit()

        flash('تم إضافة القسم بنجاح', 'success')
        log_action('create', 'department', department.id, f'إضافة قسم: {name}')
        return redirect(url_for('departments.departments'))
    return render_template('department_add.html')



@departments_bp.route('/departments/edit/<int:id>', methods=['GET', 'POST'], endpoint='department_edit')
@login_required()
def department_edit(id):
    department = Department.query.get_or_404(id)
    if request.method == 'POST':
        # طبقة 1: CSRF Protection
        if not validate_csrf_token(request.form.get('csrf_token')):
            flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
            return redirect(request.url)
        
        new_name = request.form.get('name')
        new_description = request.form.get('description') or None
        
        # طبقة 2: فحص التكرار (مع استثناء القسم الحالي)
        # نبحث عن قسم آخر (id != id الحالي) له نفس الاسم
        existing_dept = Department.query.filter(
            Department.name == new_name,
            Department.id != id
        ).first()
        
        if existing_dept:
            flash(f'خطأ: اسم القسم "{new_name}" موجود مسبقاً', 'danger')
            return redirect(url_for('departments.department_edit', id=id))
        
        # حفظ القيم القديمة قبل التحديث (للسجل)
        old_name = department.name
        old_description = department.description
        
        # تحديث البيانات
        department.name = new_name
        department.description = new_description
        db.session.commit()
        
        flash('تم تحديث بيانات القسم بنجاح', 'success')
        
        # طبقة 3: Audit Log - تسجيل التعديل مع التفاصيل
        log_action(
            'update',
            'department',
            department.id,
            f'تعديل قسم: {old_name} → {new_name}'
        )
        
        return redirect(url_for('departments.departments'))
    
    # GET request: عرض نموذج التعديل بالبيانات الحالية
    return render_template('department_edit.html', department=department)






@departments_bp.route('/departments/delete/<int:id>', methods=['POST'], endpoint='department_delete')
@login_required()
def department_delete(id):
    if not validate_csrf_token(request.form.get('csrf_token')):
        flash('رمز الأمان غير صالح، حاول مرة أخرى', 'danger')
        return redirect(request.url)
    department = Department.query.get_or_404(id)

    # فحص إذا كان القسم يحتوي على موظفين نشطين
    active_count = Employee.query.filter_by(department_id=id, status='active').count()
    inactive_count = Employee.query.filter_by(department_id=id).count() - active_count

    if active_count > 0:
        flash(f'لا يمكن حذف القسم "{department.name}" لأنه يحتوي على {active_count} موظف نشط. قم بنقل أو تعطيل الموظفين أولاً.', 'danger')
        return redirect(url_for('departments.departments'))

    if inactive_count > 0:
        flash(f'لا يمكن حذف القسم "{department.name}" لأنه يحتوي على {inactive_count} موظف غير نشط. قم بنقل أو حذف الموظفين أولاً.', 'danger')
        return redirect(url_for('departments.departments'))

    db.session.delete(department)
    db.session.commit()
    flash('تم حذف القسم بنجاح', 'success')
    log_action('delete', 'department', id, f'حذف قسم: {department.name}')
    return redirect(url_for('departments.departments'))
