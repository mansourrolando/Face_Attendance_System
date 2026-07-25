/**
 * camera-utils.js - دوال مشتركة للكاميرا
 * يُستخدم في: attendance.html, kiosk.html, register_face.html
 */

// فحص أمان الاتصال (HTTPS / localhost)
function isSecureContext() {
    return window.isSecureContext ||
           location.protocol === 'https:' ||
           location.hostname === 'localhost';
}

// تنضيف النص من HTML لمنع XSS
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ==========================================
// دوال اختيار الكاميرا
// ==========================================

// جلب قائمة الكاميرات المتاحة
async function getAvailableCameras() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
        return [];
    }
    try {
        // يجب طلب إذن الكاميرا أولاً حتى تظهر أسماء الأجهزة
        const devices = await navigator.mediaDevices.enumerateDevices();
        const videoDevices = devices.filter(d => d.kind === 'videoinput');
        return videoDevices.map((d, i) => ({
            deviceId: d.deviceId,
            label: d.label || ('كاميرا ' + (i + 1)),
            isExternal: d.label ? (d.label.toLowerCase().includes('usb') ||
                                   d.label.toLowerCase().includes('external') ||
                                   d.label.toLowerCase().includes('logitech') ||
                                   d.label.toLowerCase().includes('c920') ||
                                   d.label.toLowerCase().includes('c270') ||
                                   d.label.toLowerCase().includes('webcam') ||
                                   !d.label.toLowerCase().includes('front') &&
                                   !d.label.toLowerCase().includes('built') &&
                                   !d.label.toLowerCase().includes('integrated')) : false
        }));
    } catch (e) {
        console.error('Error enumerating devices:', e);
        return [];
    }
}

// حفظ الكاميرا المختارة
function saveSelectedCamera(deviceId) {
    try {
        localStorage.setItem('selectedCameraId', deviceId);
    } catch(e) {}
}

// جلب الكاميرا المختارة سابقاً
function getSavedCameraId() {
    try {
        return localStorage.getItem('selectedCameraId') || '';
    } catch(e) {
        return '';
    }
}

// بناء قائمة الكاميرات في عنصر select
async function populateCameraSelect(selectElement) {
    if (!selectElement) return [];

    const cameras = await getAvailableCameras();
    const savedId = getSavedCameraId();

    selectElement.innerHTML = '';

    if (cameras.length === 0) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'لم يتم العثور على كاميرات';
        selectElement.appendChild(opt);
        return cameras;
    }

    cameras.forEach((cam, i) => {
        const opt = document.createElement('option');
        opt.value = cam.deviceId;
        opt.textContent = cam.label + (cam.isExternal ? ' (خارجية)' : '');
        if (cam.deviceId === savedId) {
            opt.selected = true;
        }
        selectElement.appendChild(opt);
    });

    // إذا ما في كاميرا محفوظة، اختار الأولى
    if (!savedId && cameras.length > 0) {
        selectElement.value = cameras[0].deviceId;
    }

    return cameras;
}

// ==========================================
// تشغيل الكاميرا
// ==========================================

// تشغيل الكاميرا بالإعدادات المحددة (مع دعم deviceId)
async function initCamera(videoElement, options) {
    options = options || {};
    const width = options.width || 640;
    const height = options.height || 480;
    const deviceId = options.deviceId || getSavedCameraId() || '';

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error('NO_BROWSER_SUPPORT');
    }

    if (!isSecureContext()) {
        throw new Error('NO_SECURE_CONTEXT');
    }

    // إيقاف أي stream سابق
    if (videoElement.srcObject) {
        videoElement.srcObject.getTracks().forEach(track => track.stop());
        videoElement.srcObject = null;
    }

    // بناء constraints - إذا في deviceId استخدمو، وإلا استخدم facingMode
    let constraints;
    if (deviceId) {
        constraints = {
            video: {
                width: { ideal: width },
                height: { ideal: height },
                deviceId: { exact: deviceId }
            },
            audio: false
        };
    } else {
        constraints = {
            video: {
                width: { ideal: width },
                height: { ideal: height },
                facingMode: 'user'
            },
            audio: false
        };
    }

    const stream = await navigator.mediaDevices.getUserMedia(constraints);

    videoElement.srcObject = stream;

    await new Promise((resolve, reject) => {
        videoElement.onloadedmetadata = () => {
            videoElement.play().then(resolve).catch(reject);
        };
        videoElement.onerror = reject;
        setTimeout(() => reject(new Error('CAMERA_TIMEOUT')), 10000);
    });

    return stream;
}

// إيقاف الكاميرا
function stopStream(videoElement) {
    if (videoElement.srcObject) {
        videoElement.srcObject.getTracks().forEach(track => track.stop());
        videoElement.srcObject = null;
    }
}

// التقاط صورة من الفيديو كـ base64
function captureFrame(videoElement, canvasElement, quality) {
    quality = quality || 0.9;
    canvasElement.width = videoElement.videoWidth;
    canvasElement.height = videoElement.videoHeight;
    canvasElement.getContext('2d').drawImage(videoElement, 0, 0);
    return canvasElement.toDataURL('image/jpeg', quality);
}

// قص صورة الفيديو لمنطقة الدائرة الدليلية فقط (ضمن الدائرة بالضبط)
function cropToGuideRegion(videoEl, widthRatio, heightRatio, margin) {
    widthRatio = widthRatio || 0.50;
    heightRatio = heightRatio || 0.65;
    // margin = 1.0 يعني بالضبط ضمن الدائرة بدون زيادة
    margin = margin || 1.0;

    const vw = videoEl.videoWidth;
    const vh = videoEl.videoHeight;

    const cropW = Math.round(vw * widthRatio * margin);
    const cropH = Math.round(vh * heightRatio * margin);
    const cropX = Math.round((vw - cropW) / 2);
    const cropY = Math.round((vh - cropH) / 2);

    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = cropW;
    tempCanvas.height = cropH;
    const ctx = tempCanvas.getContext('2d');
    ctx.drawImage(videoEl, cropX, cropY, cropW, cropH, 0, 0, cropW, cropH);

    return tempCanvas.toDataURL('image/jpeg', 0.9);
}

// رسائل خطأ الكاميرا بالعربي
function getCameraErrorMessage(errorName) {
    const messages = {
        'NotAllowedError': 'تم رفض إذن الكاميرا. اضغط على أيقونة الكاميرا 📷 في شريط العنوان واختر "سماح"',
        'PermissionDeniedError': 'تم رفض إذن الكاميرا. اضغط على أيقونة الكاميرا 📷 في شريط العنوان واختر "سماح"',
        'NotFoundError': 'لم يتم العثور على كاميرا في الجهاز. تأكد من وجود كاميرا متصلة.',
        'DevicesNotFoundError': 'لم يتم العثور على كاميرا في الجهاز. تأكد من وجود كاميرا متصلة.',
        'NotReadableError': 'الكاميرا قيد الاستخدام من تطبيق آخر. أغلق أي برنامج يستخدم الكاميرا وحاول مرة أخرى.',
        'TrackStartError': 'الكاميرا قيد الاستخدام من تطبيق آخر. أغلق أي برنامج يستخدم الكاميرا وحاول مرة آخر.',
        'OverconstrainedError': 'الكاميرا المحددة غير متوفرة. قد يكون تم فصلها - اختر كاميرا أخرى.',
        'TypeError': 'الاتصال غير آمن (HTTP). الكاميرا تتطلب HTTPS أو localhost.',
        'CAMERA_TIMEOUT': 'انتهت مهلة تشغيل الكاميرا. حاول إعادة تحميل الصفحة.',
        'NO_BROWSER_SUPPORT': 'المتصفح لا يدعم الوصول للكاميرا. استخدم Chrome أو Firefox بالإصدار الأخير.',
        'NO_SECURE_CONTEXT': 'الكاميرا تحتاج اتصال آمن (HTTPS أو localhost).'
    };
    return messages[errorName] || 'خطأ غير متوقع في الكاميرا. حاول إعادة تحميل الصفحة.';
}
