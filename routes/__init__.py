def register_blueprints(app):
    """تسجيل جميع الـ Blueprints في التطبيق"""
    from .auth import auth_bp
    from .dashboard import dashboard_bp
    from .employees import employees_bp
    from .departments import departments_bp
    from .face_registration import face_bp
    from .kiosk import kiosk_bp
    from .attendance import attendance_bp
    from .attendance_manage import attendance_manage_bp
    from .attendance_calendar import attendance_calendar_bp
    from .leaves import leaves_bp
    from .tasks import tasks_bp
    from .reports import reports_bp
    from .settings_route import settings_bp
    from .audit import audit_bp
    from .holidays import holidays_bp
    from .backup import backup_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(departments_bp)
    app.register_blueprint(face_bp)
    app.register_blueprint(kiosk_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(attendance_manage_bp)
    app.register_blueprint(attendance_calendar_bp)
    app.register_blueprint(leaves_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(holidays_bp)
    app.register_blueprint(backup_bp)
