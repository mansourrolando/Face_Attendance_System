from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date as date_type

db = SQLAlchemy()


class User(db.Model):
    """مستخدم النظام (المدير)"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), default='admin')  # admin
    must_change_password = db.Column(db.Boolean, default=False)  # إجبار تغيير كلمة المرور عند أول دخول
    last_login = db.Column(db.DateTime, nullable=True)  # آخر تسجيل دخول

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Department(db.Model):
    """الأقسام"""
    __tablename__ = 'departments'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)

    # العلاقات
    employees = db.relationship('Employee', backref='department', lazy=True)

    def __repr__(self):
        return f'<Department {self.name}>'


class Employee(db.Model):
    """الموظفون"""
    __tablename__ = 'employees'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    position = db.Column(db.String(100), nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    hire_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='active')  # active, not_active
    deactivation_date = db.Column(db.Date, nullable=True)  # تاريخ التعطيل
    deactivation_reason = db.Column(db.String(50), nullable=True)  # استقالة، فصل، إنهاء عقد، إجازة طويلة، أخرى

    # بيانات التعرف على الوجه
    face_encoding = db.Column(db.LargeBinary, nullable=True)
    face_image_path = db.Column(db.String(255), nullable=True)

    # === أعمدة جديدة: رصيد الإجازات ===
    annual_leave_balance = db.Column(db.Integer, default=14)  # رصيد الإجازات السنوية بالأيام (14 يوم افتراضي)
    sick_leave_balance = db.Column(db.Integer, default=10)  # رصيد الإجازات المرضية بالأيام

    # العلاقات
    attendance_records = db.relationship('Attendance', backref='employee', lazy=True)
    leaves = db.relationship('Leave', backref='employee', lazy=True)
    tasks = db.relationship('Task', backref='employee', lazy=True)

    def __repr__(self):
        return f'<Employee {self.name}>'




class Attendance(db.Model):
    """سجلات الحضور"""
    __tablename__ = 'attendance'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=lambda: date_type.today())
    time_in = db.Column(db.Time, nullable=True)
    time_out = db.Column(db.Time, nullable=True)
    leave_out = db.Column(db.Time, nullable=True)   # وقت الخروج للإجازة الساعية
    leave_in = db.Column(db.Time, nullable=True)    # وقت الرجوع من الإجازة الساعية
    status = db.Column(db.String(20), default='present')  # present, late, leave, absent
    absence_type = db.Column(db.String(20), nullable=True)  # justified, unjustified (فقط عندما status=absent_*)
    checkout_auto = db.Column(db.Boolean, default=False)  # انصراف تلقائي (لم يسجّل انصراف يدوياً)
    notes = db.Column(db.Text, nullable=True)

    # === أعمدة جديدة: حساب ساعات العمل والتأخير والخروج المبكر ===
    work_hours = db.Column(db.Float, nullable=True)  # ساعات العمل الفعلية (بالعشرية: 8.5 = 8س 30د)
    late_minutes = db.Column(db.Integer, nullable=True, default=0)  # دقائق التأخير
    early_checkout = db.Column(db.Boolean, default=False)  # هل خرج مبكراً؟
    early_checkout_minutes = db.Column(db.Integer, nullable=True, default=0)  # دقائق الخروج المبكر

    def __repr__(self):
        return f'<Attendance {self.employee_id} {self.date}>'


class Leave(db.Model):
    """طلبات الإجازة"""
    __tablename__ = 'leaves'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    leave_type = db.Column(db.String(50), nullable=False)  # paid, unpaid, medical, maternity, hourly
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)
    reason = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    created_at = db.Column(db.DateTime, default=lambda: datetime.now())

    def __repr__(self):
        return f'<Leave {self.employee_id} {self.leave_type}>'


class Task(db.Model):
    """المهام والعمل الإضافي"""
    __tablename__ = 'tasks'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    task_type = db.Column(db.String(50), nullable=False)  # admin_task, overtime
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)
    total_hours = db.Column(db.Float, default=0)
    description = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<Task {self.employee_id} {self.task_type}>'


class Setting(db.Model):
    """إعدادات النظام"""
    __tablename__ = 'settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f'<Setting {self.key}={self.value}>'


class AuditLog(db.Model):
    """سجل نشاط النظام - يشمل المحاولات الناجحة والفاشلة"""
    __tablename__ = 'audit_log'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True)  # من قام بالإجراء (None للمحاولات الفاشلة المجهولة)
    user_name = db.Column(db.String(100), nullable=True)
    action = db.Column(db.String(50), nullable=False)  # create, update, delete, login, logout, login_failed
    entity_type = db.Column(db.String(50), nullable=True)  # employee, department, leave, task, setting
    entity_id = db.Column(db.Integer, nullable=True)
    description = db.Column(db.String(500), nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now())
    # ===== حقول جديدة للأمان والمراقبة =====
    ip_address = db.Column(db.String(45), nullable=True)  # يدعم IPv4 (15) و IPv6 (45)
    user_agent = db.Column(db.String(255), nullable=True)  # معلومات المتصفح/الجهاز
    success = db.Column(db.Boolean, default=True)  # True للإجراءات الناجحة، False للفاشلة

    def __repr__(self):
        status = '✓' if self.success else '✗'
        return f'<AuditLog {status} {self.action} by {self.user_name} from {self.ip_address}>'


class Holiday(db.Model):
    """العطل الرسمية"""
    __tablename__ = 'holidays'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)          # اسم العطلة (عيد الفطر، يوم الاستقلال...)
    date = db.Column(db.Date, nullable=False)                  # تاريخ العطلة
    holiday_type = db.Column(db.String(30), default='national')  # national, religious, government
    is_recurring = db.Column(db.Boolean, default=False)        # هل تتكرر سنوياً؟ (أعياد ثابتة التاريخ)
    notes = db.Column(db.Text, nullable=True)                  # ملاحظات

    def __repr__(self):
        return f'<Holiday {self.name} {self.date}>'

    @staticmethod
    def is_holiday(target_date):
        """فحص هل التاريخ المعطى هو عطلة رسمية (بما فيها العطل المتكررة)"""
        # عطل محددة بتاريخها
        exact = Holiday.query.filter_by(date=target_date).first()
        if exact:
            return exact

        # عطل متكررة سنوياً (نفس اليوم والشهر)
        recurring = Holiday.query.filter(
            Holiday.is_recurring == True,
            db.extract('month', Holiday.date) == target_date.month,
            db.extract('day', Holiday.date) == target_date.day
        ).first()
        if recurring:
            return recurring

        return None
class BlockedIP(db.Model):
    """عناوين IP المحظورة يدوياً من قبل المدير (Manual IP Blocking)"""
    __tablename__ = 'blocked_ips'
    
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(45), unique=True, nullable=False)  # يدعم IPv4 و IPv6
    reason = db.Column(db.String(200), nullable=True)  # سبب الحظر (brute force, scanning, ...)
    blocked_at = db.Column(db.DateTime, default=lambda: datetime.now())  # تاريخ الحظر
    blocked_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # من قام بالحظر
    
    def __repr__(self):
        return f'<BlockedIP {self.ip_address}>'