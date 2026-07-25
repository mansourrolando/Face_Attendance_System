import os
import sys
import threading
import time

# ==========================================
# إصلاح مسار المشروع - حل مشكلة "No module named app"
# ==========================================
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

os.chdir(_PROJECT_DIR)

from flask import Flask
from instance.models import db
from utils.csrf import generate_csrf_token

# إنشاء التطبيق
app = Flask(__name__)
app.config.from_object('config')

# تهيئة قاعدة البيانات
db.init_app(app)

# ==========================================
# تسجيل دوال مساعدة في Jinja2
# ==========================================
@app.context_processor
def inject_globals():
    return dict(csrf_token=generate_csrf_token)

# ==========================================
# تسجيل جميع الـ Blueprints
# ==========================================
from routes import register_blueprints
register_blueprints(app)

# ==========================================
# معالج أخطاء 404 و 500
# ==========================================
@app.errorhandler(404)
def page_not_found(e):
    from flask import render_template
    return render_template('error.html',
        error_code=404,
        error_title='الصفحة غير موجودة',
        error_message='عذراً، الصفحة التي تبحث عنها غير موجودة.'
    ), 404

@app.errorhandler(500)
def internal_error(e):
    from flask import render_template
    return render_template('error.html',
        error_code=500,
        error_title='خطأ في الخادم',
        error_message='حدث خطأ داخلي في الخادم. يرجى المحاولة لاحقاً.'
    ), 500

# ==========================================
# إنشاء الجداول والمستخدم الافتراضي
# ==========================================
with app.app_context():
    # إنشاء كل الجداول من models.py تلقائياً
    db.create_all()

    # إنشاء مستخدم admin افتراضي إذا لم يوجد
    from instance.models import User
    if not User.query.first():
        admin = User(username='admin', name='المدير', role='admin', must_change_password=True)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print("[INFO] Default admin user created: admin / admin123")

        
    # تحميل بصمات الوجوه في الذاكرة لتسريع التعرف
    try:
        from utils.face_utils import load_embeddings_cache
        load_embeddings_cache()
    except Exception as e:
        print(f"[WARN] Failed to load face embeddings cache: {e}")


# ==========================================
# خيط خلفي للانصراف التلقائي والغياب
# يفحص كل دقيقة: هل وصل وقت الانصراف التلقائي؟
# يشتغل بشكل مستقل عن فتح الصفحات
# ==========================================
def _auto_end_worker():
    """خيط خلفي - ينفذ إنهاء يوم العمل تلقائياً كل دقيقة"""
    while True:
        time.sleep(60)  # فحص كل 60 ثانية
        try:
            with app.app_context():
                from utils.absence_utils import auto_end_workday
                result = auto_end_workday()
                if result:
                    print(f"[AUTO] إنهاء يوم عمل: {result['forgot_checkouts']} انصراف تلقائي، "
                          f"{result['absent_marked']} غياب، {result['leave_marked']} إجازة")
        except Exception as e:
            print(f"[AUTO] خطأ في الخيط الخلفي: {e}")

threading.Thread(target=_auto_end_worker, daemon=True).start()
print("[INFO] خيط الانصراف التلقائي يعمل بالخلفية (فحص كل 60 ثانية)")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)