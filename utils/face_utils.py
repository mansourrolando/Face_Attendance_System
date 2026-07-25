import os
import cv2
import numpy as np
import pickle
import threading

# ==========================================
# استيراد اختياري لـ sklearn و tensorflow
# ==========================================
sklearn_available = False
try:
    from sklearn.metrics.pairwise import cosine_similarity
    sklearn_available = True
except ImportError:
    print("[WARN] scikit-learn غير متوفر - ميزة التعرف على الوجه لن تعمل")
    cosine_similarity = None

tensorflow_available = False
try:
    from tensorflow.keras.models import load_model
    tensorflow_available = True
except ImportError:
    print("[WARN] TensorFlow غير متوفر - نموذج استخراج الميزات لن يعمل")
    load_model = None

# استيراد آمن للنماذج - لا يحتاج Flask app context
try:
    from instance.models import Employee
except ImportError:
    Employee = None
    print("[WARN] لم يتم العثور على نموذج Employee - تأكد من تشغيل التطبيق من المجلد الصحيح")

from config import *

# حساب المسار المطلق لمجلد المشروع
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ==========================================
# تحميل النموذج - مرة واحدة فقط عند بدء التشغيل
# ==========================================
embedding_model = None
_model_loaded = False
_model_load_error = None


def _load_embedding_model():
    """تحميل نموذج استخراج الميزات - مرة واحدة فقط"""
    global embedding_model, _model_loaded, _model_load_error

    if _model_loaded:
        return embedding_model

    _model_loaded = True

    if not tensorflow_available:
        _model_load_error = 'TensorFlow غير مثبت - لا يمكن تحميل النموذج'
        print(f"[ERROR] {_model_load_error}")
        return None

    print("[INFO] جاري تحميل نموذج استخراج الميزات (Feature Extractor)...")

    # البحث عن نموذج V7 فقط (Custom CNN من الصفر)
    possible_paths = [
        os.path.join(_PROJECT_DIR, 'instance', 'feature_extractor_v7_scratch.h5'),
        os.path.join(_PROJECT_DIR, 'feature_extractor_v7_scratch.h5'),
        os.path.join(_PROJECT_DIR, 'models', 'feature_extractor_v7_scratch.h5'),
        os.path.abspath('feature_extractor_v7_scratch.h5'),
        os.path.abspath(os.path.join('instance', 'feature_extractor_v7_scratch.h5')),
        os.path.abspath(os.path.join('models', 'feature_extractor_v7_scratch.h5')),
    ]

    model_path = None
    for path in possible_paths:
        if os.path.exists(path):
            model_path = path
            break

    if model_path is None:
        _model_load_error = 'لم يتم العثور على ملف النموذج (feature_extractor_v7_scratch.h5)'
        print(f"[ERROR] {_model_load_error}")
        print(f"[INFO] تم البحث في:")
        for path in possible_paths:
            print(f"       - {path}")
        print(f"[INFO] مسار المشروع: {_PROJECT_DIR}")
        return None

    try:
        embedding_model = load_model(model_path)
        print(f"[OK] تم تحميل نموذج استخراج الميزات بنجاح!")
        print(f"[INFO] مسار النموذج: {model_path}")
        print(f"[INFO] شكل الإدخال: {embedding_model.input_shape}")
        print(f"[INFO] شكل الإخراج: {embedding_model.output_shape}")
    except Exception as e:
        _model_load_error = f'فشل تحميل النموذج: {e}'
        print(f"[ERROR] {_model_load_error}")
        embedding_model = None

    return embedding_model


# تحميل النموذج عند بدء التشغيل
print("[STARTUP] جاري تحميل نموذج التعرف على الوجه...")
_load_embedding_model()
if embedding_model is not None:
    print("[STARTUP] نموذج الوجه جاهز!")
else:
    print(f"[STARTUP] تحذير: النموذج غير محمل - {_model_load_error or 'سبب غير معروف'}")


# ==========================================
# محسّنات التعرف على الوجه
# ==========================================

mtcnn_available = False
try:
    from mtcnn import MTCNN
    mtcnn_detector = MTCNN()
    mtcnn_available = True
    print("[INFO] تم تحميل كاشف الوجوه MTCNN بنجاح.")
except ImportError:
    print("[INFO] MTCNN غير متوفر، سيتم استخدام Haar Cascade كبديل.")
except Exception as e:
    print(f"[WARN] فشل تهيئة MTCNN: {e}")

haar_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
haar_eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')

# استخدام متغير ديناميكي لحجم النموذج
def _get_model_input_size():
    """الحصول على حجم إدخال النموذج"""
    if embedding_model is not None:
        return embedding_model.input_shape[1]
    return 128

def _get_model_embedding_size():
    """الحصول على حجم متجه الإخراج (Embedding) من النموذج"""
    if embedding_model is not None:
        return embedding_model.output_shape[1]
    return 256

MODEL_INPUT_SIZE = _get_model_input_size()
MODEL_EMBEDDING_SIZE = _get_model_embedding_size()
print(f"[INFO] حجم البصمة (Embedding Size): {MODEL_EMBEDDING_SIZE}")

# تخزين مؤقت للمتجهات أثناء تسجيل الوجه
temp_embeddings = {}

# ==========================================
# تخزين مؤقت لمتجهات الوجه (Face Embeddings Cache)
# ==========================================
_embeddings_cache = {}  # {employee_id: {'avg': np.array, 'embeddings': [np.array, ...]}}
_cache_lock = threading.Lock()
_cache_loaded = False


def load_embeddings_cache():
    """تحميل متجهات الوجه من قاعدة البيانات إلى الذاكرة - مرة واحدة"""
    global _cache_loaded

    if _cache_loaded:
        return

    if Employee is None:
        return

    try:
        employees = Employee.query.filter(Employee.face_encoding.isnot(None)).all()
        current_embedding_size = _get_model_embedding_size()
        incompatible_count = 0
        with _cache_lock:
            _embeddings_cache.clear()
            for emp in employees:
                stored_data = pickle.loads(emp.face_encoding)
                if isinstance(stored_data, dict):
                    avg_embedding = stored_data.get('avg_embedding', None)
                    stored_embeddings = stored_data.get('embeddings', [])
                else:
                    avg_embedding = stored_data
                    stored_embeddings = []

                # فحص توافق أبعاد البصمة مع النموذج الحالي
                if avg_embedding is not None:
                    emb_array = np.array(avg_embedding)
                    if len(emb_array) != current_embedding_size:
                        incompatible_count += 1
                        continue  # تخطي البصمات غير المتوافقة

                _embeddings_cache[emp.id] = {
                    'avg': np.array(avg_embedding) if avg_embedding is not None else None,
                    'embeddings': [np.array(e) for e in stored_embeddings],
                    'employee_id': emp.employee_id,
                    'name': emp.name,
                }

        _cache_loaded = True
        loaded_count = _embeddings_cache.__len__()
        print(f"[INFO] تم تحميل {loaded_count} متجه وجه في الذاكرة المؤقتة")
        if incompatible_count > 0:
            print(f"[WARN] {incompatible_count} بصمة غير متوافقة مع النموذج الجديد (أبعاد مختلفة) - يجب إعادة تسجيل الوجه")
    except Exception as e:
        print(f"[WARN] فشل تحميل متجهات الوجه في الذاكرة: {e}")


def update_embedding_cache(employee_id, face_encoding_bytes, action='update'):
    """تحديث المتجهات المؤقتة عند إضافة/تعديل/حذف وجه"""
    with _cache_lock:
        if action == 'delete':
            _embeddings_cache.pop(employee_id, None)
            return

        try:
            stored_data = pickle.loads(face_encoding_bytes)
            if isinstance(stored_data, dict):
                avg_embedding = stored_data.get('avg_embedding', None)
                stored_embeddings = stored_data.get('embeddings', [])
            else:
                avg_embedding = stored_data
                stored_embeddings = []

            # جلب اسم الموظف ورقمه
            emp_name = ''
            emp_emp_id = ''
            if Employee is not None:
                emp = Employee.query.get(employee_id)
                if emp:
                    emp_name = emp.name
                    emp_emp_id = emp.employee_id

            _embeddings_cache[employee_id] = {
                'avg': np.array(avg_embedding) if avg_embedding is not None else None,
                'embeddings': [np.array(e) for e in stored_embeddings],
                'employee_id': emp_emp_id,
                'name': emp_name,
            }
        except Exception as e:
            print(f"[WARN] فشل تحديث المتجه المؤقت للموظف {employee_id}: {e}")


def invalidate_embedding_cache():
    """إلغاء الذاكرة المؤقتة بالكامل - يُعاد تحميلها عند الحاجة"""
    global _cache_loaded
    with _cache_lock:
        _embeddings_cache.clear()
    _cache_loaded = False


# ==========================================
# دوال مساعدة للتعرف على الوجه
# ==========================================

def l2_normalize(embedding):
    """تطبيع المتجه باستخدام L2 Normalization"""
    norm = np.linalg.norm(embedding)
    if norm == 0:
        return embedding
    return embedding / norm


def detect_face(img):
    """كشف الوجه مع دعم MTCNN و Haar Cascade - يفضل الوجه الأقرب للمركز"""
    img_h, img_w = img.shape[:2]
    center_x, center_y = img_w / 2, img_h / 2

    if mtcnn_available:
        try:
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            results = mtcnn_detector.detect_faces(img_rgb)
            if len(results) > 0:
                best = None
                best_dist = float('inf')
                for r in results:
                    x, y, w, h = r['box']
                    face_cx = x + w / 2
                    face_cy = y + h / 2
                    dist = ((face_cx - center_x) ** 2 + (face_cy - center_y) ** 2) ** 0.5
                    if dist < best_dist:
                        best_dist = dist
                        best = r

                x, y, w, h = best['box']
                x, y = max(0, x), max(0, y)
                keypoints = best.get('keypoints', {})
                left_eye = keypoints.get('left_eye', None)
                right_eye = keypoints.get('right_eye', None)
                confidence = best.get('confidence', 0)
                return {
                    'x': x, 'y': y, 'w': w, 'h': h,
                    'left_eye': left_eye, 'right_eye': right_eye,
                    'confidence': confidence, 'detector': 'mtcnn'
                }
        except Exception as e:
            print(f"[WARN] MTCNN detection failed: {e}")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray_enhanced = clahe.apply(gray)

    faces = haar_cascade.detectMultiScale(
        gray_enhanced,
        scaleFactor=1.05,
        minNeighbors=5,
        minSize=(FACE_MIN_SIZE, FACE_MIN_SIZE),
        maxSize=(400, 400),
        flags=cv2.CASCADE_SCALE_IMAGE
    )

    if len(faces) > 0:
        best_idx = 0
        best_dist = float('inf')
        for i, (fx, fy, fw, fh) in enumerate(faces):
            face_cx = fx + fw / 2
            face_cy = fy + fh / 2
            dist = ((face_cx - center_x) ** 2 + (face_cy - center_y) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_idx = i

        x, y, w, h = faces[best_idx]

        left_eye = None
        right_eye = None
        face_roi_gray = gray[y:y+h, x:x+w]
        eyes = haar_eye_cascade.detectMultiScale(face_roi_gray, 1.1, 5, minSize=(20, 20))

        if len(eyes) >= 2:
            eyes = sorted(eyes, key=lambda e: e[0])
            left_eye = (x + eyes[0][0] + eyes[0][2]//2, y + eyes[0][1] + eyes[0][3]//2)
            right_eye = (x + eyes[1][0] + eyes[1][2]//2, y + eyes[1][1] + eyes[1][3]//2)

        return {
            'x': int(x), 'y': int(y), 'w': int(w), 'h': int(h),
            'left_eye': left_eye, 'right_eye': right_eye,
            'confidence': 1.0, 'detector': 'haar'
        }

    return None


def align_face(img, face_info):
    """محاذاة الوجه بناءً على موقع العينين"""
    left_eye = face_info.get('left_eye')
    right_eye = face_info.get('right_eye')

    if left_eye is None or right_eye is None:
        x, y, w, h = face_info['x'], face_info['y'], face_info['w'], face_info['h']
        pad_w = int(w * 0.1)
        pad_h = int(h * 0.1)
        y1 = max(0, y - pad_h)
        y2 = min(img.shape[0], y + h + pad_h)
        x1 = max(0, x - pad_w)
        x2 = min(img.shape[1], x + w + pad_w)
        return img[y1:y2, x1:x2]

    dx = right_eye[0] - left_eye[0]
    dy = right_eye[1] - left_eye[1]
    angle = np.degrees(np.arctan2(dy, dx))

    center = ((left_eye[0] + right_eye[0]) // 2, (left_eye[1] + right_eye[1]) // 2)

    rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(img, rotation_matrix, (img.shape[1], img.shape[0]),
                              flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    x, y, w, h = face_info['x'], face_info['y'], face_info['w'], face_info['h']

    cos_a = np.cos(np.radians(angle))
    sin_a = np.sin(np.radians(angle))
    cx, cy = center

    new_x = cos_a * (x - cx) - sin_a * (y - cy) + cx
    new_y = sin_a * (x - cx) + cos_a * (y - cy) + cy
    x, y = int(new_x), int(new_y)

    pad_w = int(w * 0.15)
    pad_h = int(h * 0.15)
    y1 = max(0, y - pad_h)
    y2 = min(rotated.shape[0], y + h + pad_h)
    x1 = max(0, x - pad_w)
    x2 = min(rotated.shape[1], x + w + pad_w)

    return rotated[y1:y2, x1:x2]


def check_image_quality(img):
    """فحص جودة الصورة قبل المعالجة"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    if laplacian_var < FACE_BLUR_THRESHOLD:
        return False, f'الصورة ضبابية (الوضوح: {laplacian_var:.1f}، المطلوب: {FACE_BLUR_THRESHOLD}) - حاول مرة أخرى مع تثبيت الكاميرا'

    mean_brightness = np.mean(gray)
    if mean_brightness < 40:
        return False, 'الصورة مظلمة جداً - حاول في مكان بإضاءة أفضل'
    if mean_brightness > 230:
        return False, 'الصورة فاترة جداً (إضاءة زائدة) - حاول تقليل الإضاءة'

    std_dev = np.std(gray)
    if std_dev < 20:
        return False, 'تباين الصورة منخفض جداً - حاول في مكان بإضاءة متوازنة'

    return True, 'الجودة مقبولة'


def extract_embedding(face_img):
    """استخراج المتجه من صورة الوجه مع تطبيع L2"""
    global embedding_model

    if embedding_model is None:
        raise RuntimeError('نموذج التعرف على الوجه غير محمل' + (f' - {_model_load_error}' if _model_load_error else ''))

    model_size = _get_model_input_size()
    face_rgb = cv2.cvtColor(face_img, cv2.COLOR_BGR2RGB)
    face_resized = cv2.resize(face_rgb, (model_size, model_size))
    face_normalized = face_resized / 255.0
    input_img = np.expand_dims(face_normalized, axis=0)

    embedding = embedding_model.predict(input_img, verbose=0)[0]

    if FACE_NORMALIZE_EMBEDDINGS:
        embedding = l2_normalize(embedding)

    return embedding


def process_face_image(img):
    """المعالجة الكاملة لصورة الوجه - يأخذ الوجه الأقرب للمركز فقط"""
    quality_ok, quality_msg = check_image_quality(img)
    if not quality_ok:
        return False, quality_msg, None

    face_info = detect_face(img)
    if face_info is None:
        return False, 'لم يتم اكتشاف وجه! تأكد من مواجهة الكاميرا مباشرة', None

    if face_info['w'] < FACE_MIN_SIZE or face_info['h'] < FACE_MIN_SIZE:
        return False, f'الوجه صغير جداً ({face_info["w"]}x{face_info["h"]}) - اقترب أكثر من الكاميرا', None

    face_aligned = align_face(img, face_info)

    if face_aligned.size == 0:
        return False, 'خطأ في استخراج الوجه', None

    embedding = extract_embedding(face_aligned)

    return True, 'تم بنجاح', embedding


def find_best_match(input_embedding):
    """البحث عن أفضل تطابق مع فحص الفجوة - يستخدم الذاكرة المؤقتة"""
    if Employee is None:
        return None, 0, 'نموذج Employee غير متوفر'

    if not sklearn_available:
        return None, 0, 'scikit-learn غير متوفر - لا يمكن حساب التشابه'

    # تحميل الذاكرة المؤقتة إذا لم تكن محملة
    if not _cache_loaded:
        load_embeddings_cache()

    # إذا الذاكرة المؤقتة فارغة، استخدم الطريقة القديمة
    with _cache_lock:
        if not _embeddings_cache:
            return _find_best_match_db(input_embedding)

    # البحث في الذاكرة المؤقتة (أسرع بكثير)
    scores = []
    with _cache_lock:
        for emp_id, cache_data in _embeddings_cache.items():
            avg_embedding = cache_data.get('avg')
            stored_embeddings = cache_data.get('embeddings', [])

            avg_score = 0
            if avg_embedding is not None:
                avg_score = cosine_similarity([input_embedding], [avg_embedding])[0][0]

            max_single_score = 0
            for stored_emb in stored_embeddings:
                score = cosine_similarity([input_embedding], [stored_emb])[0][0]
                if score > max_single_score:
                    max_single_score = score

            final_score = max(avg_score, max_single_score)
            scores.append((emp_id, final_score))

    if not scores:
        return None, 0, 'لا يوجد موظفون مسجلون في النظام'

    scores.sort(key=lambda x: x[1], reverse=True)

    best_emp_id = scores[0][0]
    best_score = scores[0][1]

    # جلب كائن الموظف من قاعدة البيانات
    best_match = Employee.query.get(best_emp_id)
    if best_match is None:
        # إذا لم يوجد، نلغي الذاكرة المؤقتة ونعيد المحاولة
        invalidate_embedding_cache()
        return _find_best_match_db(input_embedding)

    if best_score < FACE_RECOGNITION_THRESHOLD:
        return None, best_score, f'لم يتم التعرف عليك (أعلى تشابه: {best_score:.2f}، المطلوب: {FACE_RECOGNITION_THRESHOLD})'

    if len(scores) > 1:
        second_score = scores[1][1]
        gap = best_score - second_score

        if gap < FACE_GAP_THRESHOLD:
            second_emp = Employee.query.get(scores[1][0])
            second_name = second_emp.name if second_emp else 'غير معروف'
            return None, best_score, (
                f'النظام مش متأكد! تشابه عالي مع شخصين: '
                f'{best_match.name} ({best_score:.2f}) و {second_name} ({second_score:.2f}) '
                f'- الفرق ({gap:.2f}) أقل من المطلوب ({FACE_GAP_THRESHOLD})'
            )

    return best_match, best_score, 'تم التعرف بنجاح'


def _find_best_match_db(input_embedding):
    """البحث عن تطابق من قاعدة البيانات مباشرة - fallback"""
    employees = Employee.query.filter(Employee.face_encoding.isnot(None)).all()

    if not employees:
        return None, 0, 'لا يوجد موظفون مسجلون في النظام'

    current_embedding_size = len(input_embedding)
    scores = []
    for emp in employees:
        stored_data = pickle.loads(emp.face_encoding)

        if isinstance(stored_data, dict):
            stored_embeddings = stored_data.get('embeddings', [])
            avg_embedding = stored_data.get('avg_embedding', None)
        else:
            stored_embeddings = []
            avg_embedding = stored_data

        # فحص توافق الأبعاد
        if avg_embedding is not None:
            avg_emb_array = np.array(avg_embedding)
            if len(avg_emb_array) != current_embedding_size:
                continue  # تخطي البصمات غير المتوافقة

        if avg_embedding is not None:
            avg_score = cosine_similarity([input_embedding], [avg_embedding])[0][0]
        else:
            avg_score = 0

        max_single_score = 0
        for stored_emb in stored_embeddings:
            score = cosine_similarity([input_embedding], [stored_emb])[0][0]
            if score > max_single_score:
                max_single_score = score

        final_score = max(avg_score, max_single_score)
        scores.append((emp, final_score, avg_score, max_single_score))

    scores.sort(key=lambda x: x[1], reverse=True)

    best_match = scores[0][0]
    best_score = scores[0][1]

    if best_score < FACE_RECOGNITION_THRESHOLD:
        return None, best_score, f'لم يتم التعرف عليك (أعلى تشابه: {best_score:.2f}، المطلوب: {FACE_RECOGNITION_THRESHOLD})'

    if len(scores) > 1:
        second_score = scores[1][1]
        gap = best_score - second_score

        if gap < FACE_GAP_THRESHOLD:
            second_name = scores[1][0].name
            return None, best_score, (
                f'النظام مش متأكد! تشابه عالي مع شخصين: '
                f'{best_match.name} ({best_score:.2f}) و {second_name} ({second_score:.2f}) '
                f'- الفرق ({gap:.2f}) أقل من المطلوب ({FACE_GAP_THRESHOLD})'
            )

    return best_match, best_score, 'تم التعرف بنجاح'