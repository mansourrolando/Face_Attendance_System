# models/ — مجلد نموذج التعرف على الوجه
# ضع ملف feature_extractor_v7_scratch.h5 هنا
# نموذج Keras: مدخل 160x160x3 → مخرج 512 embedding
# V7 - Custom CNN من الصفر (بدون نموذج جاهز)
# المعمارية: 5 Conv Blocks (32→64→128→256→512) + GAP + Dense(1024) + Dense(512)
# التدريب: 2572 شخص، 330K صورة، 3 مراحل (LR: 1e-3 → 1e-4 → 1e-5)
# النتائج على LFW: Rank-1=45.26%, AUC=0.9832, Verification=94.83%
# احتياطي: feature_extractor_v6_all.h5 (MobileNetV2 - لا يُستخدم)
