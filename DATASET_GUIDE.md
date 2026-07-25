# 📊 دليل إعداد مجموعة بيانات الاختبار (Test Dataset Guide)

هذا الدليل يشرح كيفية إعداد مجموعات بيانات الاختبار لتقييم نظام التعرف على الوجه ونظام كشف الشاشات.

---

## 📁 البنية المطلوبة

### 1. مجموعة بيانات تقييم نموذج الوجه (Face Recognition Test Set)

```
evaluation/
└── datasets/
    └── face_test_set/
        ├── person_001/        ← مجلد لكل شخص
        │   ├── img1.jpg       ← صورة 1 (للتسجيل)
        │   ├── img2.jpg       ← صورة 2 (للاختبار)
        │   ├── img3.jpg
        │   ├── img4.jpg
        │   └── img5.jpg
        ├── person_002/
        │   ├── img1.jpg
        │   └── ...
        ├── person_003/
        └── ...
```

**المتطلبات:**
- 5-10 صور لكل شخص (بزوايا وإضاءة مختلفة)
- الحد الأدنى: شخص واحد بصورتين (واحدة للتسجيل وواحدة للاختبار)
- الموصى به لاختبار جاد: 20-50 شخص × 5 صور = 100-250 صورة
- الصيغة: JPG, PNG, BMP
- الدقة: 720p على الأقل
- حجم الوجه: 60 بكسل على الأقل

### 2. مجموعة بيانات كشف الشاشات (Anti-Spoofing Test Set)

```
evaluation/
└── datasets/
    └── anti_spoof_test_set/
        ├── real/             ← صور وجوه حقيقية
        │   ├── img1.jpg
        │   ├── img2.jpg
        │   └── ...
        └── screen/           ← صور من شاشات
            ├── img1.jpg      ← صورة من شاشة هاتف
            ├── img2.jpg      ← صورة من شاشة تابلت
            └── ...
```

**المتطلبات:**
- 50-250 صورة حقيقية (real/)
- 50-250 صورة شاشة (screen/)
- تنوع الشاشات: LCD, OLED, Retina, AMOLED
- تنوع زوايا التصوير: أمامي، مائل، مختلف المسافات
- تنوع الإضاءة: طبيعي، منخفض، مرتفع

---

## 📸 كيفية جمع البيانات

### وجوه حقيقية (real/)

1. **من متطوعين:** اطلب من 10-20 صديق التقاط 5 صور لكل واحد منهم
2. **من قواعد بيانات مفتوحة:**
   - **LFW (Labeled Faces in the Wild):** http://vis-www.cs.umass.edu/lfw/
   - **CASIA-WebFace:** https://kpzhang93.github.io/MTCNN_face_detection_alignment/
   - **UTKFace:** https://susanqq.github.io/UTKFace/
3. **من صورك الخاصة:** صور مناسبات عائلية، صور شركة

### صور الشاشات (screen/)

1. **التقط صوراً لشاشة هاتفك** تعرض صور وجوه
2. **استخدم شاشات متنوعة:**
   - هاتف iPhone (شاشة OLED)
   - هاتف Android (LCD أو OLED)
   - تابلت iPad
   - شاشة لاب توب
3. **تنوع زوايا التصوير:**
   - عمودي 90 درجة
   - مائل 30 درجة
   - مائل 45 درجة
4. **تنوع الإضاءة:**
   - غرفة مظلمة (شاشة ساطعة)
   - غرفة مضيئة (شاشة طبيعية)
   - سطوع الشاشة: 100%, 50%, 25%

---

## 🛠️ سكربت مساعد لجمع الصور من الكاميرا

أنشئ ملف `capture_test_images.py` لتسهيل جمع الصور:

```python
"""
سكربت لجمع صور الاختبار من الكاميرا
يحفظ الصور تلقائياً بالبنية المطلوبة
"""
import cv2
import os
import sys

def capture_real_faces(output_dir, person_name, num_images=5):
    """التقاط صور وجوه حقيقية"""
    person_dir = os.path.join(output_dir, person_name)
    os.makedirs(person_dir, exist_ok=True)
    
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("خطأ: لا يمكن فتح الكاميرا")
        return
    
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    )
    
    count = 0
    print(f"التقاط {num_images} صور لـ {person_name}")
    print("اضغط SPACE للالتقاط، Q للخروج")
    
    while count < num_images:
        ret, frame = cap.read()
        if not ret:
            break
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)
        
        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
        
        cv2.putText(frame, f"Image {count}/{num_images}", (10, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imshow('Capture - SPACE=Capture, Q=Quit', frame)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord(' '):
            img_path = os.path.join(person_dir, f"img{count+1}.jpg")
            cv2.imwrite(img_path, frame)
            print(f"تم حفظ: {img_path}")
            count += 1
        elif key == ord('q'):
            break
    
    cap.release()
    cv2.destroyAllWindows()
    print(f"تم التقاط {count} صورة")

if __name__ == '__main__':
    person_name = sys.argv[1] if len(sys.argv) > 1 else "test_person"
    capture_real_faces("datasets/face_test_set", person_name)
```

---

## ⚠️ قواعد مهمة لضمان صحة التقييم

### 1. تجنب تسرّب البيانات (Data Leakage)

❌ **خطأ:** صور الشخص الواحد موجودة في كل من training set و test set
✅ **صحيح:** صور الشخص الواحد تكون كلها إما في training أو في test، وليس في كليهما

### 2. تنوّع البيانات

للحصول على نتائج واقعية، تأكد من:
- **وجوه متنوعة:** أعمار مختلفة، أجناس مختلفة، جنسين
- **إضاءة متنوعة:** طبيعية، صناعية، منخفضة، عالية
- **زوايا مختلفة:** أمامي، مائل يميناً، مائل يساراً، للأعلى، للأسفل
- **تعبيرات مختلفة:** محايد، ابتسامة، نظارات، بدون نظارات

### 3. حجم كافٍ

| نوع الاختبار | الحد الأدنى | الموصى به |
|---|---|---|
| تعرف على الوجه | 5 أشخاص × 5 صور | 50+ شخص × 5 صور |
| كشف الشاشات | 50 صورة حقيقية + 50 شاشة | 250+ من كل نوع |

---

## 📋 سكربت فحص الـ Dataset قبل التقييم

```python
"""
سكربت فحص الـ dataset قبل التقييم
يتحقق من البنية وحجم الصور
"""
import os
import cv2
from pathlib import Path

def check_face_dataset(dataset_path):
    """فحص dataset التعرف على الوجه"""
    print(f"\nفحص dataset: {dataset_path}")
    print("-" * 50)
    
    total_images = 0
    persons = 0
    
    for person_name in os.listdir(dataset_path):
        person_dir = os.path.join(dataset_path, person_name)
        if not os.path.isdir(person_dir):
            continue
        
        images = [f for f in os.listdir(person_dir) 
                 if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        
        if images:
            persons += 1
            total_images += len(images)
            print(f"  {person_name}: {len(images)} صورة")
            
            # فحص حجم أول صورة
            img_path = os.path.join(person_dir, images[0])
            img = cv2.imread(img_path)
            if img is not None:
                h, w = img.shape[:2]
                print(f"    حجم الصورة: {w}x{h}")
    
    print("-" * 50)
    print(f"الإجمالي: {persons} شخص، {total_images} صورة")
    
    if persons < 5:
        print("⚠️  تحذير: عدد الأشخاص قليل جداً (أقل من 5)")
    if total_images < 25:
        print("⚠️  تحذير: عدد الصور قليل جداً (أقل من 25)")

def check_anti_spoofing_dataset(dataset_path):
    """فحص dataset كشف الشاشات"""
    print(f"\nفحص dataset كشف الشاشات: {dataset_path}")
    print("-" * 50)
    
    for category in ['real', 'screen']:
        cat_dir = os.path.join(dataset_path, category)
        if not os.path.exists(cat_dir):
            print(f"  ⚠️  مجلد {category} غير موجود!")
            continue
        
        images = [f for f in os.listdir(cat_dir)
                 if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        
        print(f"  {category}: {len(images)} صورة")
        
        if len(images) < 30:
            print(f"    ⚠️  قليل جداً (أقل من 30)")

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        path = sys.argv[1]
        if 'face' in path.lower():
            check_face_dataset(path)
        else:
            check_anti_spoofing_dataset(path)
    else:
        print("استخدام: python check_dataset.py <dataset_path>")
```

---

## 📝 مصادر البيانات الموصى بها (مفتوحة المصدر)

### قواعد بيانات الوجوه

1. **LFW (Labeled Faces in the Wild)**
   - الرابط: http://vis-www.cs.umass.edu/lfw/
   - الحجم: 13,000+ صورة لـ 1,680 شخص
   - الاستخدام: مفتوح للأبحاث

2. **CASIA-WebFace**
   - الرابط: https://kpzhang93.github.io/MTCNN_face_detection_alignment/
   - الحجم: 494,414 صورة لـ 10,575 شخص
   - الاستخدام: مفتوح للأبحاث

3. **UTKFace**
   - الرابط: https://susanqq.github.io/UTKFace/
   - الحجم: 20,000+ صورة
   - الاستخدام: مفتوح للأبحاث

### قواعد بيانات Anti-Spoofing

1. **CASIA-FASD (Face Anti-Spoofing Database)**
   - الرابط: http://www.cbsr.ia.ac.cn/english/FaceAntiSpoofDatabases.asp
   - الحجم: 50 شخص، 600 فيديو
   - الأنواع: print, photo, video attacks

2. **Replay-Attack Database**
   - الرابط: https://www.idiap.ch/dataset/replayattack
   - الحجم: 1,300+ فيديو
   - الأنواع: print, mobile, high-def

3. **NUAA Photograph Imposter Database**
   - الرابط: http://www.cs.nju.edu.cn/rlawml/imposterDB.html
   - الحجم: 5,105 صورة لـ 15 شخص

---

## ✅ قائمة التحقق النهائية

قبل تشغيل سكربتات التقييم، تأكد من:

- [ ] مجلد `face_test_set/` يحتوي على مجلدات أشخاص منفصلة
- [ ] كل مجلد شخص يحتوي على 2 صور على الأقل
- [ ] لا توجد صورة لنفس الشخص في training و test set
- [ ] مجلد `anti_spoof_test_set/` يحتوي على مجلدين: `real/` و `screen/`
- [ ] كل مجلد يحتوي على 30+ صورة
- [ ] صور الشاشات متنوعة (LCD, OLED, 不同 شاشات)
- [ ] ملف النموذج `feature_extractor_v7_scratch.h5` موجود في `instance/`
- [ ] المكتبات المطلوبة مثبتة: `pip install -r requirements.txt`

---

## 🚀 تشغيل التقييم

```bash
# 1. انتقل لمجلد التقييم
cd evaluation

# 2. شغّل تقييم نموذج الوجه
python evaluate_face_model.py \
    --dataset datasets/face_test_set \
    --model ../instance/feature_extractor_v7_scratch.h5 \
    --enrollment-count 1 \
    --output-dir results

# 3. شغّل تقييم كشف الشاشات
python evaluate_anti_spoofing.py \
    --dataset datasets/anti_spoof_test_set \
    --output-dir results

# 4. اعرض النتائج
cat results/evaluation_report.txt
cat results/anti_spoofing_report.txt
```

النتائج ستكون في مجلد `results/`:
- `metrics.json` - مقاييس نموذج الوجه بصيغة JSON
- `anti_spoofing_metrics.json` - مقاييس كشف الشاشات
- `detailed_results.csv` - تفاصيل كل صورة
- `roc_curve.png` - منحنى ROC
- `confusion_matrix.png` - مصفوفة الالتباس
- `evaluation_report.txt` - تقرير نصي قابل للقراءة

---

**ملاحظة:** إذا كانت لديك مجموعة بيانات صغيرة (10-20 صورة)، يمكنك تشغيل التقييم لكن النتائج ستكون تقريبية. للحصول على نتائج دقيقة وموثوقة، يُفضّل استخدام 100+ صورة على الأقل.
