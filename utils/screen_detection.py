"""
كشف الشاشات (Screen Detection) - النسخة v2.0
يمنع الاحتيال عن طريق عرض صورة الوجه على شاشة هاتف/تابلت

المبدأ الأساسي - كشف نمط Moiré:
عند تصوير شاشة هاتف بالكاميرا، شبكة بكسلات الشاشة تتداخل
مع شبكة بكسلات الكاميرا وتنتج نمط Moiré (خطوط متكررة أفقية/عمودية)
هذا النمط يظهر في مجال التردد (FFT) كنقاط ساطعة على المحاور الأفقية والعمودية

التقنيات المستخدمة:
1. كشف Moiré متعدد المقاييس بـ FFT (الأساسي - وزن 30%)
2. كشف الدورية بالارتباط التلقائي (وزن 20%)
3. تحليل الملمس/التباين (وزن 20%)
4. تحليل لوني (وزن 15%)
5. كشف الانعكاسات (وزن 15%)

القيود:
- فقط cv2 + numpy (لا نماذج ML إضافية)
- يعمل على إطار واحد (سريع)
"""

import cv2
import numpy as np

# ==========================================
# الإعدادات الافتراضية (تُقرأ من config.py)
# ==========================================

try:
    from config import SCREEN_DETECTION_ENABLED
except ImportError:
    SCREEN_DETECTION_ENABLED = True

try:
    from config import SCREEN_FFT_THRESHOLD
except ImportError:
    SCREEN_FFT_THRESHOLD = 0.10

try:
    from config import SCREEN_TEXTURE_THRESHOLD
except ImportError:
    SCREEN_TEXTURE_THRESHOLD = 60.0

try:
    from config import SCREEN_EDGE_THRESHOLD
except ImportError:
    SCREEN_EDGE_THRESHOLD = 0.08

try:
    from config import SCREEN_MIN_FACE_SIZE
except ImportError:
    SCREEN_MIN_FACE_SIZE = 40

try:
    from config import SCREEN_COLOR_SCORE_WEIGHT
except ImportError:
    SCREEN_COLOR_SCORE_WEIGHT = 0.15

try:
    from config import SCREEN_DECISION_THRESHOLD
except ImportError:
    SCREEN_DECISION_THRESHOLD = 0.40


# ==========================================
# 1. كشف نمط Moiré متعدد المقاييس (FFT)
# ==========================================

def _find_peaks_in_profile(profile, min_height_ratio=1.5):
    """
    البحث عن قمم في ملف ترددي

    المعاملات:
        profile: مصفوفة 1D
        min_height_ratio: الحد الأدنى لارتفاع القمة نسبة للمتوسط

    يعيد: قائمة بالقمم (القيم المطلقة)
    """
    if len(profile) < 5:
        return []

    mean_val = np.mean(profile)
    if mean_val < 1e-6:
        return []

    peaks = []
    # تجاهل أول 15% (قريبة جداً من DC)
    start_idx = max(1, len(profile) // 7)

    for i in range(start_idx, len(profile) - 1):
        if profile[i] > profile[i - 1] and profile[i] > profile[i + 1]:
            if profile[i] > mean_val * min_height_ratio:
                peaks.append(float(profile[i]))

    return peaks


def _detect_moire_fft(face_gray):
    """
    كشف نمط Moiré باستخدام تحليل FFT

    المبدأ:
    - الشاشات تنتج أنماط دورية أفقية/عمودية (شبكة البكسلات)
    - هذه الأنماط تظهر كنقاط ساطعة على المحاور في مجال التردد
    - نحلل الملف الأفقي والعمودي للطيف ونبحث عن قمم

    يعيد: (moire_score 0-1, detail_dict)
    """
    h, w = face_gray.shape
    if h < 20 or w < 20:
        return 0.0, {}

    # تطبيع الصورة
    face_float = face_gray.astype(np.float64)
    mean_val = np.mean(face_float)
    std_val = np.std(face_float)
    if std_val < 1e-6:
        return 0.0, {'reason': 'صورة موحدة'}
    face_norm = (face_float - mean_val) / std_val

    # نافذة Hanning لتقليل التأثيرات الحدية (مهم جداً)
    hann_h = np.hanning(h).reshape(-1, 1)
    hann_w = np.hanning(w).reshape(1, -1)
    hanning_2d = hann_h * hann_w
    windowed = face_norm * hanning_2d

    # تحويل فورييه 2D
    f = np.fft.fft2(windowed)
    fshift = np.fft.fftshift(f)
    magnitude = np.abs(fshift)

    # Log-magnitude spectrum (أفضل للكشف عن القمم)
    log_mag = np.log1p(magnitude)

    crow, ccol = h // 2, w // 2

    # ==========================================
    # تحليل الملف الأفقي (متوسط كل صف من الطيف)
    # القمم هنا = ترددات عمودية = خطوط أفقية في الصورة الأصلية
    # ==========================================
    h_profile = np.mean(log_mag, axis=1)

    # ندمج النصفين (تقريباً متماثل)
    h_left = h_profile[:crow]
    h_right = h_profile[crow + 1:]
    min_len = min(len(h_left), len(h_right))
    h_merged = (h_left[:min_len] + h_right[::-1][:min_len]) / 2.0

    h_peaks = _find_peaks_in_profile(h_merged, min_height_ratio=1.5)
    h_mean = float(np.mean(h_merged)) if len(h_merged) > 0 else 0

    # ==========================================
    # تحليل الملف العمودي (متوسط كل عمود من الطيف)
    # القمم هنا = ترددات أفقية = خطوط عمودية في الصورة الأصلية
    # ==========================================
    v_profile = np.mean(log_mag, axis=0)

    v_left = v_profile[:ccol]
    v_right = v_profile[ccol + 1:]
    min_len_v = min(len(v_left), len(v_right))
    v_merged = (v_left[:min_len_v] + v_right[::-1][:min_len_v]) / 2.0

    v_peaks = _find_peaks_in_profile(v_merged, min_height_ratio=1.5)
    v_mean = float(np.mean(v_merged)) if len(v_merged) > 0 else 0

    # ==========================================
    # حساب قوة القمم
    # ==========================================
    def peak_strength(peaks, mean):
        if not peaks or mean < 1e-6:
            return 0.0, 0
        max_p = max(peaks)
        strength = max_p / mean
        important = len([p for p in peaks if p > mean * 2.0])
        return strength, important

    h_strength, h_important = peak_strength(h_peaks, h_mean)
    v_strength, v_important = peak_strength(v_peaks, v_mean)

    max_strength = max(h_strength, v_strength)
    total_important = h_important + v_important

    # ==========================================
    # حساب درجة Moiré (0-1)
    # ==========================================
    moire_score = 0.0

    # أ: قمة قوية جداً (أهم مؤشر)
    if max_strength > 3.5:
        moire_score += 0.45
    elif max_strength > 3.0:
        moire_score += 0.35
    elif max_strength > 2.5:
        moire_score += 0.25
    elif max_strength > 2.0:
        moire_score += 0.15

    # ب: قمم متعددة = نمط دوري واضح
    if total_important >= 4:
        moire_score += 0.25
    elif total_important >= 3:
        moire_score += 0.20
    elif total_important >= 2:
        moire_score += 0.15
    elif total_important >= 1:
        moire_score += 0.08

    # ج: قمم على كلا المحورين = شبكة (أقوى دليل على شاشة)
    if h_strength > 2.0 and v_strength > 2.0:
        moire_score += 0.20
    elif h_strength > 1.8 and v_strength > 1.8:
        moire_score += 0.10

    # د: نسبة الطاقة في الترددات العالية
    # نحسبها بشكل مختلف عن v1 - نستخدم منطقة محورية بدل دائرية
    # محور أفقي: صف مركزي +/- 3 صفوف
    # محور عمودي: عمود مركزي +/- 3 أعمدة
    axis_w = max(3, min(7, w // 20))
    axis_h = max(3, min(7, h // 20))

    h_axis_energy = np.sum(log_mag[crow - axis_h:crow + axis_h, :])
    v_axis_energy = np.sum(log_mag[:, ccol - axis_w:ccol + axis_w])
    total_energy = np.sum(log_mag) + 1e-6

    axis_ratio = (h_axis_energy + v_axis_energy) / total_energy
    if axis_ratio > 0.08:
        moire_score += 0.10
    elif axis_ratio > 0.06:
        moire_score += 0.05

    moire_score = min(moire_score, 1.0)

    detail = {
        'h_peak_strength': round(float(h_strength), 3),
        'v_peak_strength': round(float(v_strength), 3),
        'h_important_peaks': h_important,
        'v_important_peaks': v_important,
        'total_important_peaks': total_important,
        'max_peak_strength': round(float(max_strength), 3),
        'axis_energy_ratio': round(float(axis_ratio), 4),
        'face_size': f'{w}x{h}',
    }

    return float(moire_score), detail


def _detect_moire_multiscale(face_gray):
    """
    كشف Moiré على عدة مقاييس

    يفحص الصورة الأصلية + نسخة مكبرة 2x و 1.5x
    لأن نمط Moiré قد يظهر بترددات مختلفة حسب مسافة الشاشة

    يعيد: (best_score, detail_dict)
    """
    h, w = face_gray.shape

    # المقياس الأصلي
    score1, detail1 = _detect_moire_fft(face_gray)
    best_score = score1
    best_detail = detail1

    # تكبير 1.5x (إذا كان الوجه كبير كفاية)
    if h >= 50 and w >= 50:
        h15 = int(h * 1.5)
        w15 = int(w * 1.5)
        scaled = cv2.resize(face_gray, (w15, h15), interpolation=cv2.INTER_CUBIC)
        score15, detail15 = _detect_moire_fft(scaled)
        if score15 > best_score:
            best_score = score15
            best_detail = detail15
            best_detail['scale'] = '1.5x'

    # تكبير 2x (إذا كان الوجه كبير كفاية)
    if h >= 40 and w >= 40:
        h2 = h * 2
        w2 = w * 2
        scaled2 = cv2.resize(face_gray, (w2, h2), interpolation=cv2.INTER_CUBIC)
        score2, detail2 = _detect_moire_fft(scaled2)
        if score2 > best_score:
            best_score = score2
            best_detail = detail2
            best_detail['scale'] = '2.0x'

    return float(best_score), best_detail


# ==========================================
# 2. كشف الدورية بالارتباط التلقائي
# ==========================================

def _detect_periodicity(face_gray):
    """
    كشف الأنماط الدورية باستخدام الارتباط التلقائي

    المبدأ:
    - الشاشات تنتج أنماطاً دورية (بكسلات، خطوط مسح)
    - الارتباط التلقائي يكشف التكرار حتى لو لم يكن واضحاً بصرياً
    - نحلل الارتباط على الصفوف والأعمدة بشكل منفصل

    يعيد: (periodicity_score 0-1, detail_dict)
    """
    h, w = face_gray.shape
    if h < 30 or w < 30:
        return 0.0, {}

    face_float = face_gray.astype(np.float64)
    periodicity_score = 0.0

    # ==========================================
    # أ: دورية أفقية (تكرار عمودي = خطوط أفقية)
    # نأخذ متوسط الصفوف ونحسب الارتباط التلقائي
    # ==========================================
    row_means = np.mean(face_float, axis=1)
    row_means = row_means - np.mean(row_means)
    row_autocorr = np.correlate(row_means, row_means, mode='full')
    # نأخذ النصف الموجب فقط
    row_autocorr = row_autocorr[len(row_means) - 1:]
    # نطبّع
    if row_autocorr[0] > 0:
        row_autocorr = row_autocorr / row_autocorr[0]

    # البحث عن قمم في الارتباط التلقائي (بعد أول 3 عينات)
    row_peaks = []
    for i in range(3, len(row_autocorr) - 1):
        if row_autocorr[i] > row_autocorr[i - 1] and row_autocorr[i] > row_autocorr[i + 1]:
            if row_autocorr[i] > 0.1:
                row_peaks.append((i, float(row_autocorr[i])))

    # ==========================================
    # ب: دورية عمودية (تكرار أفقي = خطوط عمودية)
    # ==========================================
    col_means = np.mean(face_float, axis=0)
    col_means = col_means - np.mean(col_means)
    col_autocorr = np.correlate(col_means, col_means, mode='full')
    col_autocorr = col_autocorr[len(col_means) - 1:]
    if col_autocorr[0] > 0:
        col_autocorr = col_autocorr / col_autocorr[0]

    col_peaks = []
    for i in range(3, len(col_autocorr) - 1):
        if col_autocorr[i] > col_autocorr[i - 1] and col_autocorr[i] > col_autocorr[i + 1]:
            if col_autocorr[i] > 0.1:
                col_peaks.append((i, float(col_autocorr[i])))

    # ==========================================
    # ج: تحليل النتائج
    # ==========================================
    # قوة أقوى قمة دورية
    row_max_corr = max([p[1] for p in row_peaks], default=0)
    col_max_corr = max([p[1] for p in col_peaks], default=0)
    max_corr = max(row_max_corr, col_max_corr)

    # عدد القمم الدورية القوية
    strong_row_peaks = len([p for p in row_peaks if p[1] > 0.3])
    strong_col_peaks = len([p for p in col_peaks if p[1] > 0.3])
    total_strong = strong_row_peaks + strong_col_peaks

    if max_corr > 0.6:
        periodicity_score += 0.4
    elif max_corr > 0.4:
        periodicity_score += 0.25
    elif max_corr > 0.25:
        periodicity_score += 0.15

    if total_strong >= 3:
        periodicity_score += 0.35
    elif total_strong >= 2:
        periodicity_score += 0.25
    elif total_strong >= 1:
        periodicity_score += 0.15

    # إذا وجدنا دورية على كلا المحورين
    if row_max_corr > 0.3 and col_max_corr > 0.3:
        periodicity_score += 0.15

    periodicity_score = min(periodicity_score, 1.0)

    # فترة الدورية الأقوى (لتشخيص)
    best_row_period = row_peaks[0][0] if row_peaks else 0
    best_col_period = col_peaks[0][0] if col_peaks else 0

    detail = {
        'row_max_corr': round(float(row_max_corr), 4),
        'col_max_corr': round(float(col_max_corr), 4),
        'row_strong_peaks': strong_row_peaks,
        'col_strong_peaks': strong_col_peaks,
        'total_strong_peaks': total_strong,
        'row_period': best_row_period,
        'col_period': best_col_period,
    }

    return float(periodicity_score), detail


# ==========================================
# 3. تحليل الملمس (Texture Analysis)
# ==========================================

def _analyze_texture(face_gray):
    """
    تحليل ملمس الوجه

    البشرة الحقيقية: تفاوت عالٍ (مسام، تجاعيد، ظلال طبيعية)
    شاشة العرض: تفاوت منخفض (صورة مسطحة، بكسلات منتظمة)

    يعيد: (texture_screen_score 0-1, detail_dict)
    """
    # Laplacian Variance - المقياس الأساسي
    laplacian = cv2.Laplacian(face_gray, cv2.CV_64F)
    laplacian_var = float(np.var(laplacian))

    # مقياس Gabor-like: تحليل التباين المحلي بـ CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    enhanced = clahe.apply(face_gray)
    enhanced_var = float(np.var(enhanced))

    # مقياس التباين الإقليمي
    h, w = face_gray.shape
    quarter_vars = []
    for i in range(2):
        for j in range(2):
            region = face_gray[i * h // 2:(i + 1) * h // 2,
                            j * w // 2:(j + 1) * w // 2]
            quarter_vars.append(float(np.var(region)))
    region_var_std = float(np.std(quarter_vars))
    region_var_mean = float(np.mean(quarter_vars))

    # ==========================================
    # حساب درجة الشاشة (0 = حقيقي، 1 = شاشة)
    # ==========================================
    texture_screen_score = 0.0

    # A: Laplacian منخفض = ملمس مسطح = مشبوه
    if laplacian_var < SCREEN_TEXTURE_THRESHOLD * 0.5:
        texture_screen_score += 0.4
    elif laplacian_var < SCREEN_TEXTURE_THRESHOLD * 0.7:
        texture_screen_score += 0.25
    elif laplacian_var < SCREEN_TEXTURE_THRESHOLD:
        texture_screen_score += 0.15

    # B: تباين المناطق متساوٍ = صورة مسطحة
    if region_var_std < 5:
        texture_screen_score += 0.25
    elif region_var_std < 15:
        texture_screen_score += 0.15

    # C: التباين المحلي منخفض
    if enhanced_var < 300:
        texture_screen_score += 0.2
    elif enhanced_var < 500:
        texture_screen_score += 0.1

    texture_screen_score = min(texture_screen_score, 1.0)

    detail = {
        'laplacian_var': round(laplacian_var, 2),
        'enhanced_var': round(enhanced_var, 2),
        'region_var_std': round(region_var_std, 2),
        'region_var_mean': round(region_var_mean, 2),
        'threshold': SCREEN_TEXTURE_THRESHOLD,
    }

    return float(texture_screen_score), detail


# ==========================================
# 4. تحليل لوني (Color Analysis)
# ==========================================

def _analyze_color(face_bgr):
    """
    تحليل لوني لكشف الشاشات

    الشاشات غالباً:
    - تنتج ألواناً مشبعة أكثر أو أقل من الطبيعي
    - تفتقر للتدرجات اللونية الدقيقة
    - تظهر انعكاسات زرقاء/خضراء خفيفة
    - عدد الألوان الفريدة أقل من البشرة الحقيقية

    يعيد: (color_score 0-1, detail_dict)
    """
    hsv = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2HSV)

    s_channel = hsv[:, :, 1]
    v_channel = hsv[:, :, 2]

    sat_mean = float(np.mean(s_channel))
    sat_std = float(np.std(s_channel))
    val_mean = float(np.mean(v_channel))
    val_std = float(np.std(v_channel))

    color_score = 0.0

    # تشبع شاذ
    if sat_mean > 140:
        color_score += 0.2
    elif sat_mean < 15:
        color_score += 0.15

    # تباين التشبع منخفض (صورة مسطحة)
    if sat_std < 10:
        color_score += 0.2
    elif sat_std < 15:
        color_score += 0.1

    # كشف انعكاسات الشاشة (نسبة الأزرق للأحمر)
    b, g, r = cv2.split(face_bgr)
    blue_red_ratio = float(np.mean(b)) / (float(np.mean(r)) + 1e-6)
    if blue_red_ratio > 1.15:
        color_score += 0.15

    # تباين السطوع منخفض (صورة مسطحة لونياً)
    if val_std < 30:
        color_score += 0.15
    elif val_std < 45:
        color_score += 0.08

    # عدد الألوان الفريدة (quantized)
    # الشاشات عادة تنتج ألوان أقل من البشرة الحقيقية
    small = cv2.resize(face_bgr, (32, 32), interpolation=cv2.INTER_AREA)
    small_lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
    l_channel = small_lab[:, :, 0]
    a_channel = small_lab[:, :, 1]
    b_channel = small_lab[:, :, 2]
    # تقدير عدد الألوان الفريدة بتقريب القيم
    l_bins = np.histogram(l_channel, bins=8)[0]
    nonzero_bins = np.count_nonzero(l_bins)
    if nonzero_bins < 4:
        color_score += 0.10

    color_score = min(color_score, 1.0)

    detail = {
        'sat_mean': round(sat_mean, 2),
        'sat_std': round(sat_std, 2),
        'val_mean': round(val_mean, 2),
        'val_std': round(val_std, 2),
        'blue_red_ratio': round(blue_red_ratio, 3),
        'color_bins_used': int(nonzero_bins),
    }

    return float(color_score), detail


# ==========================================
# 5. كشف الانعكاسات (Reflection Analysis)
# ==========================================

def _analyze_reflections(face_bgr):
    """
    كشف الانعكاسات على سطح الشاشة

    شاشات الهاتف لها سطح زجاجي لامع ينتج:
    - بقع سطوع عالية محلية (specular highlights)
    - انعكاسات حادة غير منتشرة
    - تباين عالي جداً في مناطق صغيرة

    البشرة الحقيقية:
    - انعكاس منتشر (diffuse)
    - لا توجد بقع سطوع حادة صغيرة

    يعيد: (reflection_score 0-1, detail_dict)
    """
    gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    reflection_score = 0.0

    # ==========================================
    # أ: كشف البقع الساطعة جداً (Specular highlights)
    # ==========================================
    # عتبة عالية جداً - فقط البقع شديدة السطوع
    _, bright_mask = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY)
    bright_ratio = float(np.count_nonzero(bright_mask)) / gray.size

    if bright_ratio > 0.02:
        reflection_score += 0.25
    elif bright_ratio > 0.008:
        reflection_score += 0.15
    elif bright_ratio > 0.003:
        reflection_score += 0.08

    # ==========================================
    # ب: تحليل حدة البقع الساطعة
    # ==========================================
    # Laplacian على الصورة يكشف الحواف الحادة
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)

    # في مناطق السطوع العالي، إذا كان Laplacian عالي = حواف حادة = انعكاس
    bright_areas = (gray > 200).astype(np.float64)
    laplacian_in_bright = np.abs(laplacian) * bright_areas
    bright_laplacian_mean = float(np.sum(laplacian_in_bright)) / (np.sum(bright_areas) + 1e-6)

    if bright_laplacian_mean > 30:
        reflection_score += 0.25
    elif bright_laplacian_mean > 15:
        reflection_score += 0.15

    # ==========================================
    # ج: تباين حواف الشاشة (Screen border detection)
    # ==========================================
    # نحلل حواف الصورة الكبيرة (ليس الوجه فقط)
    # الشاشة غالباً لها حواف مستقيمة وحادة
    edges = cv2.Canny(gray, 80, 200)

    # نحلل حواف الحدود (أول وآخر 10% من كل بُعد)
    border_h = max(1, h // 10)
    border_w = max(1, w // 10)

    # الحواف العلوية والسفلية
    top_edges = np.count_nonzero(edges[:border_h, :])
    bottom_edges = np.count_nonzero(edges[h - border_h:, :])
    left_edges = np.count_nonzero(edges[:, :border_w])
    right_edges = np.count_nonzero(edges[:, w - border_w:])

    border_edge_total = top_edges + bottom_edges + left_edges + right_edges
    border_area = 2 * (border_h * w + border_w * h) + 1e-6
    border_edge_density = float(border_edge_total) / border_area

    # المناطق الداخلية
    inner_edges = np.count_nonzero(edges[border_h:h - border_h, border_w:w - border_w])
    inner_area = (h - 2 * border_h) * (w - 2 * border_w) + 1e-6
    inner_edge_density = float(inner_edges) / inner_area

    # إذا كانت الحواف على الحدود أعلى بكثير من الداخل = إطار شاشة
    if inner_edge_density > 0:
        border_inner_ratio = border_edge_density / inner_edge_density
    else:
        border_inner_ratio = 0

    if border_inner_ratio > 2.0 and border_edge_density > 0.05:
        reflection_score += 0.30
    elif border_inner_ratio > 1.5 and border_edge_density > 0.03:
        reflection_score += 0.20
    elif border_edge_density > 0.08:
        reflection_score += 0.15

    reflection_score = min(reflection_score, 1.0)

    detail = {
        'bright_ratio': round(bright_ratio, 4),
        'bright_laplacian_mean': round(bright_laplacian_mean, 2),
        'border_edge_density': round(border_edge_density, 4),
        'inner_edge_density': round(inner_edge_density, 4),
        'border_inner_ratio': round(border_inner_ratio, 3),
    }

    return float(reflection_score), detail


# ==========================================
# 6. تحليل الشاشة المعتمة (Dark Screen Detection)
# ==========================================

def _analyze_dark_screen(face_gray, face_bgr, color_detail, texture_detail):
    """
    كشف الشاشات ذات السطوع المنخفض

    عند خفض سطوع الهاتف، المحددات التقليدية تفشل لأن:
    - Moire يضعف (تباين بكسلات منخفض)
    - السطوع لا يدل على شاشة (val_mean منخفض)
    - الانعكاسات تقل

    لكن الشاشة المعتمة لها توقيع فريد مختلف عن الوجه الحقيقي المعتم:
    - تباين موحد (flat) — الوجه الحقيقي فيه ظلال 3D
    - عدد ألوان قليل جداً
    - تباين السطوع منخفض جداً (شاشة معتمة = موحد)
    - الملمس شبه صفري

    يعيد: (dark_screen_score 0-1, detail_dict)
    """
    val_mean = color_detail.get('val_mean', 128)
    val_std = color_detail.get('val_std', 50)
    laplacian_var = texture_detail.get('laplacian_var', 100)
    sat_std = color_detail.get('sat_std', 30)
    color_bins = color_detail.get('color_bins_used', 8)
    enhanced_var = texture_detail.get('enhanced_var', 500)

    dark_screen_score = 0.0

    # نفعّل هذا التحليل فقط إذا السطوع منخفض أو متوسط
    # رفعت العتبة لـ 175 عشان نغطي حالة خفض السطوع المتوسط
    if val_mean > 175:
        return 0.0, {'active': False, 'reason': 'سطوع عالي - لا حاجة'}

    # ==========================================
    # أ: الملمس شبه صفري (أقوى مؤشر)
    # ==========================================
    # شاشة معتمة: بكسلات متقاربة السطوع = Laplacian شبه صفري
    # وجه حقيقي معتم: فيه ظلال 3D (الأنف، العينين) تعطي Laplacian > 15
    if laplacian_var < 8:
        dark_screen_score += 0.35
    elif laplacian_var < 15:
        dark_screen_score += 0.25
    elif laplacian_var < 25:
        dark_screen_score += 0.15

    # ==========================================
    # ب: تباين السطوع منخفض جداً
    # ==========================================
    # شاشة معتمة = موحدة السطوع، val_std منخفض
    # وجه حقيقي معتم = فيه تفاوت (ظلال الأنف، العينين، الفم)
    if val_std < 12:
        dark_screen_score += 0.25
    elif val_std < 20:
        dark_screen_score += 0.15

    # ==========================================
    # ج: عدد ألوان فريد قليل جداً
    # ==========================================
    # الشاشة المعتمة تنتج تدرج رمادي محدود
    # الوجه الحقيقي حتى المعتم فيه ألوان أكثر
    if color_bins <= 2:
        dark_screen_score += 0.20
    elif color_bins <= 3:
        dark_screen_score += 0.12

    # ==========================================
    # د: تباين التشبع منخفض (صورة مسطحة)
    # ==========================================
    if sat_std < 8:
        dark_screen_score += 0.10
    elif sat_std < 12:
        dark_screen_score += 0.05

    # ==========================================
    # هـ: CLAHE enhanced variance منخفض جداً
    # ==========================================
    # حتى CLAHE ما بيفيد مع شاشة معتمة لأن مفيش تفاوت لتعزيزه
    if enhanced_var < 100:
        dark_screen_score += 0.15
    elif enhanced_var < 200:
        dark_screen_score += 0.08

    # ==========================================
    # و: تحليل توزيع السطوع (Histogram shape)
    # ==========================================
    # شاشة معتمة: الـ histogram ضيق ومتمركز في نطاق ضيق
    # وجه حقيقي: histogram أعرض (ظلال + إضاءة)
    hist = cv2.calcHist([face_gray], [0], None, [64], [0, 256]).flatten()
    hist_norm = hist / (hist.sum() + 1e-6)

    # نسبة البكسلات في أضيق 16 مستوى من الـ 64 حول الوسط
    center_bin = int(val_mean / 4)
    spread = 8
    start_bin = max(0, center_bin - spread)
    end_bin = min(64, center_bin + spread)
    narrow_ratio = float(np.sum(hist_norm[start_bin:end_bin]))

    if narrow_ratio > 0.85:
        dark_screen_score += 0.15
    elif narrow_ratio > 0.75:
        dark_screen_score += 0.08

    # ==========================================
    # ز: فحص حواف الوجه (Edge density)
    # ==========================================
    # الوجه الحقيقي المعتم لا يزال لديه حواف (contours)
    # الشاشة المعتمة: حواف قليلة جداً
    edges = cv2.Canny(face_gray, 30, 80)
    edge_density = float(np.count_nonzero(edges)) / edges.size

    if edge_density < 0.01:
        dark_screen_score += 0.15
    elif edge_density < 0.02:
        dark_screen_score += 0.08

    # ==========================================
    # ح: تأكيد الوجه الحقيقي (مضادات للإنذار الكاذب)
    # ==========================================
    # حتى لو السطوع منخفض، هذه المؤشرات تؤكد بشرة حقيقية
    # الوجه الحقيقي المعتم: ملمس (sensor noise)، حواف (ظلال 3D)، تفاوت سطوع
    # الشاشة المعتمة: أملس، بلا حواف، موحد السطوع
    # نحتاج مؤشرين على الأقل من 3 لإلغاء نتيجة الشاشة المعتمة
    real_indicators = 0
    if laplacian_var > 30:
        real_indicators += 1
    if val_std > 22:
        real_indicators += 1
    if edge_density > 0.025:
        real_indicators += 1

    if real_indicators >= 2:
        # وجه حقيقي مؤكد رغم السطوع المنخفض
        detail = {
            'active': True,
            'real_face_confirmed': True,
            'real_indicators': real_indicators,
            'val_mean': val_mean,
            'val_std': val_std,
            'laplacian_var': laplacian_var,
            'edge_density': round(edge_density, 4),
            'color_bins': color_bins,
        }
        return 0.0, detail
    elif real_indicators == 1:
        # مؤشر واحد فقط - نخفض الدرجة بشكل كبير
        dark_screen_score *= 0.25

    dark_screen_score = min(dark_screen_score, 1.0)

    detail = {
        'active': True,
        'real_face_confirmed': False,
        'real_indicators': real_indicators,
        'val_mean': val_mean,
        'val_std': val_std,
        'laplacian_var': laplacian_var,
        'narrow_hist_ratio': round(narrow_ratio, 4),
        'edge_density': round(edge_density, 4),
        'color_bins': color_bins,
    }

    return float(dark_screen_score), detail


# ==========================================
# الدالة الرئيسية: كشف الشاشة
# ==========================================

def detect_screen(frame, face_box=None):
    """
    فحص شامل لكشف ما إذا كان الوجه معروضاً على شاشة

    المعاملات:
        frame: إطار OpenCV (BGR)
        face_box: dict أو None - معلومات الوجه {'x', 'y', 'w', 'h'}
                  إذا كان None، سيتم كشف الوجه تلقائياً

    يعيد: dict يحتوي على:
        is_screen: bool
        confidence: float (0-1)
        scores: dict
        details: dict
        message: str
    """
    if not SCREEN_DETECTION_ENABLED:
        return {
            'is_screen': False,
            'confidence': 0.0,
            'scores': {},
            'details': {},
            'message': 'كشف الشاشة معطل'
        }

    # ==========================================
    # كشف الوجه إذا لم يتم تمريره
    # ==========================================
    if face_box is None:
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        gray_full = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray_enhanced = clahe.apply(gray_full)
        faces = face_cascade.detectMultiScale(
            gray_enhanced, scaleFactor=1.05, minNeighbors=5,
            minSize=(SCREEN_MIN_FACE_SIZE, SCREEN_MIN_FACE_SIZE)
        )
        if len(faces) == 0:
            return {
                'is_screen': False, 'confidence': 0.0,
                'scores': {}, 'details': {},
                'message': 'لم يتم كشف وجه'
            }
        best = max(faces, key=lambda f: f[2] * f[3])
        face_box = {'x': int(best[0]), 'y': int(best[1]),
                    'w': int(best[2]), 'h': int(best[3])}

    x = face_box.get('x', 0)
    y = face_box.get('y', 0)
    w = face_box.get('w', 0)
    h = face_box.get('h', 0)

    if w < SCREEN_MIN_FACE_SIZE or h < SCREEN_MIN_FACE_SIZE:
        return {
            'is_screen': False, 'confidence': 0.0,
            'scores': {}, 'details': {},
            'message': f'الوجه صغير جداً ({w}x{h})'
        }

    # ==========================================
    # استخراج منطقة الوجه + هامش كبير (مهم لكشف حواف الشاشة)
    # ==========================================
    img_h, img_w = frame.shape[:2]

    # هامش 40% حول الوجه (كبير لكشف حواف الشاشة المحتملة)
    margin_x = int(w * 0.40)
    margin_y = int(h * 0.40)

    rx1 = max(0, x - margin_x)
    ry1 = max(0, y - margin_y)
    rx2 = min(img_w, x + w + margin_x)
    ry2 = min(img_h, y + h + margin_y)

    roi_bgr = frame[ry1:ry2, rx1:rx2]
    if roi_bgr.size == 0:
        return {
            'is_screen': False, 'confidence': 0.0,
            'scores': {}, 'details': {},
            'message': 'منطقة التحليل فارغة'
        }

    roi_gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)

    # منطقة الوجه فقط (داخل ROI)
    inner_x = x - rx1
    inner_y = y - ry1
    face_bgr = roi_bgr[inner_y:inner_y + h, inner_x:inner_x + w]
    face_gray = roi_gray[inner_y:inner_y + h, inner_x:inner_x + w]

    if face_bgr.size == 0 or face_gray.size == 0:
        return {
            'is_screen': False, 'confidence': 0.0,
            'scores': {}, 'details': {},
            'message': 'منطقة الوجه فارغة'
        }

    # ==========================================
    # التحليل الذكي: مقارنة الهامش vs. الوجه
    # المبدأ: على شاشة الهاتف، Moiré يكون أقوى في الهامش
    # (حواف الشاشة) منه في منطقة الوجه (الصورة المعروضة)
    # على الوجه الحقيقي، Moiré يكون موزع بالتساوي
    # ==========================================
    margin_moire_score, margin_moire_detail = _detect_moire_multiscale(roi_gray)
    face_moire_score, face_moire_detail = _detect_moire_multiscale(face_gray)

    # حساب فرق Moiré بين الهامش والوجه
    moire_ratio = 0.0
    if face_moire_score > 0.05:
        moire_ratio = margin_moire_score / face_moire_score
    elif margin_moire_score > 0.2:
        # Moiré في الهامش بس = مؤشر قوي جداً على شاشة
        moire_ratio = 5.0  # قيمة عالية تدل على شاشة

    # استخراج تفاصيل القمم FFT (مهمة لكشف شبكة البكسلات)
    face_important_peaks = face_moire_detail.get('total_important_peaks', 0)
    face_max_peak_str = face_moire_detail.get('max_peak_strength', 0)
    face_h_peaks = face_moire_detail.get('h_important_peaks', 0)
    face_v_peaks = face_moire_detail.get('v_important_peaks', 0)
    margin_important_peaks = margin_moire_detail.get('total_important_peaks', 0)
    margin_axis_energy = margin_moire_detail.get('axis_energy_ratio', 0)

    # ==========================================
    # تشغيل التحليلات الأربعة الباقية (على الوجه فقط)
    # ==========================================

    # 2. الدورية
    periodicity_score, periodicity_detail = _detect_periodicity(face_gray)

    # 3. الملمس
    texture_score, texture_detail = _analyze_texture(face_gray)

    # 4. اللون
    color_score, color_detail = _analyze_color(face_bgr)

    # 5. الانعكاسات (يحلل ROI الكاملة مع الهامش)
    reflection_score, reflection_detail = _analyze_reflections(roi_bgr)

    # 6. تحليل الشاشة المعتمة (مهم جداً لكشف الشاشات بخفض السطوع)
    dark_screen_score, dark_screen_detail = _analyze_dark_screen(
        face_gray, face_bgr, color_detail, texture_detail
    )

    # ==========================================
    # حساب الدرجة النهائية الموزونة
    # ==========================================
    final_score = (
        0.30 * face_moire_score +
        0.20 * periodicity_score +
        0.20 * texture_score +
        0.15 * color_score +
        0.15 * reflection_score
    )

    # ==========================================
    # قواعد حسم ذكية - تعتمد على المقارنة بين الهامش والوجه
    # ==========================================

    # ==========================================
    # استخراج قيم السطوع (الأكثر موثوقية)
    # ==========================================
    bright_r = reflection_detail.get('bright_ratio', 0)
    bright_lap_mean = reflection_detail.get('bright_laplacian_mean', 0)
    val_m = color_detail.get('val_mean', 0)

    # ==========================================
    # حماية الوجه الحقيقي (مهم جداً!)
    # ==========================================
    # المبدأ: على شاشة الموبايل الحقيقية، Moiré يكون أقوى على الهامش
    # (حواف الشاشة) منه على منطقة الوجه (الصورة المعروضة).
    # أما على الوجه الحقيقي، إذا ظهر Moiré (ضوضاء كاميرا/إضاءة)
    # فيكون موزع بالتساوي — نسبة الهامش/الوجه قريبة من 1.0
    # نستخدم هذا الفرق لمنع الرفض الخاطئ للوجوه الحقيقية.

    real_face_protection = False

    # ==========================================
    # نظام الحماية المتدرجة (3 مستويات)
    # ==========================================
    # مؤشران موثوقان:
    # 1. val_mean (سطوع): وجه حقيقي < 148، شاشة > 149
    # 2. periodicity (دورية): وجه حقيقي <= 0.15، شاشة = 0.30
    #    ⚠️ periodicity = 0.30 فاصل واضح بين الوجه والشاشة!
    # ==========================================

    # === كشف مؤشرات الشاشة القوية (قبل الحماية) ===
    screen_signal = 0
    if periodicity_score >= 0.25 and face_moire_score >= 0.5:
        screen_signal += 1  # دورية + مويريه = شاشة
    if val_m > 155 and margin_moire_score > 0.3:
        screen_signal += 1  # سطوع عالي = شاشة

    protection_level = 0  # 0=بلا, 1=خفيفة, 2=كاملة
    protection_reason = ''

    # === المستوى 2: حماية كاملة (وجه حقيقي مؤكد) ===
    if val_m < 150 and screen_signal == 0:
        protection_level = 2
        protection_reason = f'val_mean={val_m:.1f} < 150 + لا إشارة شاشة'
    # === المستوى 1: حماية خفيفة (منطقة رمادية) ===
    elif val_m < 158 and screen_signal == 0:
        if moire_ratio < 1.3:
            non_moire_indicators = [texture_score, color_score, reflection_score]
            strong_non_moire = sum(1 for s in non_moire_indicators if s > 0.25)
            if strong_non_moire == 0:
                protection_level = 2
                protection_reason = f'val_mean={val_m:.1f} (رمادي) + لا مؤشرات قوية'
            elif strong_non_moire == 1:
                protection_level = 1
                protection_reason = f'val_mean={val_m:.1f} (رمادي) + مؤشر قوي واحد'
    # === المستوى 0: بلا حماية ===
    # val_mean >= 158 أو screen_signal > 0 → الحماية لا تفعّل

    # === استثناء الشاشة المعتمة ===
    if dark_screen_score >= 0.4:
        protection_level = 0
        protection_reason = f'dark_screen={dark_screen_score:.2f} >= 0.4 (شاشة معتمة مؤكدة)'
    elif dark_screen_score >= 0.25:
        if protection_level == 2:
            protection_level = 1
            protection_reason = f'dark_screen={dark_screen_score:.2f} → تخفيض حماية'

    # ==========================================
    # قواعد حسم ذكية - تعتمد على المقارنة بين الهامش والوجه
    # ==========================================

    # قاعدة 1 (الأقوى): Moiré في الهامش أكبر بكثير من الوجه
    # هذا الدليل الأقوى على شاشة — البكسلات ظاهرة على الحواف بس
    if moire_ratio >= 2.5 and margin_moire_score >= 0.25:
        final_score = max(final_score, SCREEN_DECISION_THRESHOLD + 0.15)

    # قاعدة 2: Moiré في الهامش عالي + نسبة تدعم الشاشة + دليل إضافي
    # ⚠️ استثناء محسّن: نستثني فقط إذا val_mean منخفض + ما في دليل شاشة معتمة
    elif margin_moire_score >= 0.4 and moire_ratio >= 1.5:
        if val_m < 150 and dark_screen_score < 0.3:
            pass  # سطوع منخفض + ما في دليل شاشة معتمة = وجه حقيقي
        else:
            secondary_evidence = (periodicity_score > 0.15 or texture_score > 0.15
                                  or color_score > 0.15 or reflection_score > 0.15
                                  or dark_screen_score > 0.3)
            if secondary_evidence:
                final_score = max(final_score, SCREEN_DECISION_THRESHOLD + 0.10)

    # قاعدة 3: دورية + مويريه قوي = شاشة (الأكثر موثوقية بعد السطوع!)
    # ⚠️ بيانات حقيقية: كل شاشات الموبايل تعطي periodicity=0.30
    # والوجه الحقيقي يعطي periodicity <= 0.15 → فاصل واضح!
    if periodicity_score >= 0.25 and face_moire_score >= 0.5:
        final_score = max(final_score, SCREEN_DECISION_THRESHOLD + 0.05)

    # قاعدة 3b: دورية عالية جداً + مويريه عالي = شاشة مؤكدة
    if face_moire_score >= 0.6 and periodicity_score >= 0.4:
        final_score = max(final_score, SCREEN_DECISION_THRESHOLD + 0.10)

    # قاعدة 3.5: النسبة شديدة الانعكاس + moiré قوي + دورية = شاشة
    # هذا يحدث لما صورة الوجه على الشاشة تفصيلية (moiré بالوجه قوي)
    # والهامش خلفية معتمة (moiré بالهامش ضعيف) → ratio < 0.6
    # الوجه الحقيقي نادراً يعطي ratio < 0.6 لأن moiré الضوضاء متوزع بالتساوي
    if moire_ratio < 0.55 and face_moire_score >= 0.45 and periodicity_score >= 0.20:
        final_score = max(final_score, SCREEN_DECISION_THRESHOLD + 0.03)

    # قاعدة 4: 3 مؤشرات أو أكثر فوق 0.25
    high_indicators = sum(1 for s in [face_moire_score, periodicity_score, texture_score,
                                        color_score, reflection_score] if s > 0.25)
    if high_indicators >= 3:
        final_score = max(final_score, SCREEN_DECISION_THRESHOLD + 0.08)

    # قاعدة 5: فحص السطوع (الأكثر موثوقية!)
    # الشاشات تكون أسطع من الوجوه الحقيقية
    # val_mean > 155 = سطوع شاشة (الوجه الحقيقي غالباً < 142)
    # ⚠️ ما نستخدم bright_ratio لأن الكاميرا تعطي قيمة أعلى للوجه الحقيقي
    if val_m > 155 and margin_moire_score > 0.3:
        final_score = max(final_score, SCREEN_DECISION_THRESHOLD + 0.05)

    # ==========================================
    # قواعد كشف الشاشة المعتمة (Dark Screen Rules)
    # تفعّل عندما يخفض المستخدم سطوع الموبايل
    # ==========================================

    # قاعدة 6: شاشة معتمة قوية - أقوى دليل على شاشة بخفض السطوع
    if dark_screen_score >= 0.6:
        final_score = max(final_score, SCREEN_DECISION_THRESHOLD + 0.15)
    elif dark_screen_score >= 0.45:
        final_score = max(final_score, SCREEN_DECISION_THRESHOLD + 0.10)
    elif dark_screen_score >= 0.35:
        # تحتاج دليل داعم واحد على الأقل
        if texture_score > 0.1 or periodicity_score > 0.1:
            final_score = max(final_score, SCREEN_DECISION_THRESHOLD + 0.05)

    # قاعدة 7: شاشة معتمة + ملمس مسطح = شاشة مؤكدة
    # الوجه الحقيقي حتى المعتم فيه ملمس (ظلال 3D)
    # الشاشة المعتمة = مسطحة تماماً
    if dark_screen_score >= 0.4 and texture_score >= 0.25:
        final_score = max(final_score, SCREEN_DECISION_THRESHOLD + 0.15)

    # قاعدة 8: شاشة معتمة + دليل إضافي (انعكاس أو دورية أو لون)
    if dark_screen_score >= 0.3 and (reflection_score > 0.1 or periodicity_score > 0.15
                                     or color_score > 0.15):
        final_score = max(final_score, SCREEN_DECISION_THRESHOLD + 0.05)

    # قاعدة 9: شاشة معتمة + Moiré في الهامش = شاشة مؤكدة 100%
    # حتى لو Moiré ضعيف، وجوده مع شاشة معتمة = تأكيد
    if dark_screen_score >= 0.3 and margin_moire_score >= 0.15:
        final_score = max(final_score, SCREEN_DECISION_THRESHOLD + 0.10)

    # ==========================================
    # تطبيق الحماية المتدرجة (بعد كل القواعد)
    # ==========================================
    # ⚠️ لا يوجد قواعد تجاوز الحماية — الحماية نهائية
    # val_mean < 150 = وجه حقيقي مؤكد → لا يمكن تجاوز الحماية
    # الشاشات تُكتشف بقاعدة 5 (val_m > 155) قبل تطبيق الحماية
    # ==========================================
    if protection_level == 2:
        final_score = min(final_score, SCREEN_DECISION_THRESHOLD - 0.05)
    elif protection_level == 1:
        final_score = min(final_score, SCREEN_DECISION_THRESHOLD)

    # ==========================================
    # القرار النهائي
    # ==========================================
    is_screen = final_score >= SCREEN_DECISION_THRESHOLD

    # ==========================================
    # بناء الرسالة
    # ==========================================
    if is_screen:
        indicators = []
        if margin_moire_score > 0.3:
            indicators.append(f'Moiré هامش ({margin_moire_score:.0%})')
        if face_moire_score > 0.3:
            indicators.append(f'Moiré وجه ({face_moire_score:.0%})')
        if moire_ratio >= 2.0:
            indicators.append(f'نسبة هامش/وجه={moire_ratio:.1f}x')
        if periodicity_score > 0.3:
            indicators.append(f'دورية ({periodicity_score:.0%})')
        if dark_screen_score > 0.3:
            indicators.append(f'شاشة معتمة ({dark_screen_score:.0%})')
        if texture_score > 0.3:
            indicators.append('ملمس مسطح')
        if color_score > 0.3:
            indicators.append('ألوان مشبوهة')
        if reflection_score > 0.3:
            indicators.append('انعكاسات شاشة')
        message = 'تم كشف شاشة! ' + ' | '.join(indicators) if indicators else 'تم كشف شاشة!'
    else:
        message = 'الوجه حقيقي (لا مؤشرات على شاشة)'

    # ==========================================
    # تنظيف القيم وتجهيز النتيجة
    # ==========================================
    def _clean(val):
        if isinstance(val, (np.bool_, bool)):
            return bool(val)
        elif isinstance(val, (np.integer,)):
            return int(val)
        elif isinstance(val, (np.floating,)):
            return float(val)
        elif isinstance(val, np.ndarray):
            return val.tolist()
        elif isinstance(val, dict):
            return {k: _clean(v) for k, v in val.items()}
        elif isinstance(val, (list, tuple)):
            return [_clean(v) for v in val]
        return val

    return _clean({
        'is_screen': is_screen,
        'confidence': round(final_score, 4),
        'threshold': SCREEN_DECISION_THRESHOLD,
        'protection_level': protection_level,
        'protection_reason': protection_reason,
        'scores': {
            'moire': round(face_moire_score, 4),
            'margin_moire': round(margin_moire_score, 4),
            'moire_ratio': round(moire_ratio, 2),
            'periodicity': round(periodicity_score, 4),
            'texture': round(texture_score, 4),
            'color': round(color_score, 4),
            'reflection': round(reflection_score, 4),
            'dark_screen': round(dark_screen_score, 4),
        },
        'details': {
            'moire': face_moire_detail,
            'margin_moire': margin_moire_detail,
            'periodicity': periodicity_detail,
            'texture': texture_detail,
            'color': color_detail,
            'reflection': reflection_detail,
            'dark_screen': dark_screen_detail,
        },
        'message': message,
    })


# ==========================================
# دالة تشخيص سريعة
# ==========================================

def quick_screen_check(frame, face_box=None):
    """
    فحص سريع - يعيد (is_screen, confidence, message)
    """
    result = detect_screen(frame, face_box)
    return result['is_screen'], result['confidence'], result['message']
