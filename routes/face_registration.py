from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from datetime import date
import os
import cv2
import numpy as np
import pickle
import base64
from sklearn.metrics.pairwise import cosine_similarity
from instance.models import db, Employee
from utils.face_utils import embedding_model, detect_face, l2_normalize, process_face_image, temp_embeddings, update_embedding_cache
from utils.helpers import get_setting, login_required
from config import *

face_bp = Blueprint('face', __name__)


@face_bp.route('/register_face_page/<int:id>', endpoint='register_face_page')
@login_required()
def register_face_page(id):
    employee = Employee.query.get_or_404(id)
    reg_images = int(get_setting('registration_images', str(FACE_REGISTRATION_IMAGES)))
    return render_template('register_face.html', employee=employee, total_images=reg_images)

@face_bp.route('/register_face/<int:id>', methods=['POST'], endpoint='register_face')
@login_required(api=True)
def register_face(id):
    if embedding_model is None:
        return jsonify({'success': False, 'message': 'النموذج غير محمل'})

    employee = Employee.query.get_or_404(id)
    reg_images = int(get_setting('registration_images', str(FACE_REGISTRATION_IMAGES)))

    try:
        data = request.get_json()
        image_data = data['image'].split(',')[1]
        image_bytes = base64.b64decode(image_data)
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        success, message, embedding = process_face_image(img)

        if not success:
            return jsonify({'success': False, 'message': message})

        if id not in temp_embeddings:
            temp_embeddings[id] = []

        if len(temp_embeddings[id]) > 0:
            for prev_emb in temp_embeddings[id]:
                sim = cosine_similarity([embedding], [prev_emb])[0][0]
                if sim < FACE_REGISTRATION_MIN_SIMILARITY:
                    return jsonify({
                        'success': False,
                        'message': f'هذه الصورة مختلفة عن الصور السابقة (تشابه: {sim:.2f}). تأكد من تصوير نفس الشخص!'
                    })

        temp_embeddings[id].append(embedding)
        count = len(temp_embeddings[id])

        face_info = detect_face(img)
        if face_info:
            x, y, w, h = face_info['x'], face_info['y'], face_info['w'], face_info['h']
            face_img = img[y:y+h, x:x+w]
            filename = f"{employee.employee_id}_img{count}.jpg"
            filepath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'faces', filename)
            os.makedirs(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'faces'), exist_ok=True)
            cv2.imwrite(filepath, face_img)

        if count < reg_images:
            tips = {
                1: 'التقط صورة من زاوية مختلفة (مثلاً مع إمالة بسيطة)',
                2: 'التقط صورة مع ابتسامة خفيفة',
                3: 'التقط صورة أخيرة بتعبير محايد',
                4: 'التقط صورة بإضاءة مختلفة قليلاً',
            }
            tip = tips.get(count, 'التقط صورة أخرى بزاوية مختلفة')
            return jsonify({
                'success': True,
                'message': f'تم حفظ الصورة {count} من {reg_images} - {tip}',
                'status': 'collecting',
                'count': count,
                'total': reg_images
            })

        embeddings_array = np.array(temp_embeddings[id])
        avg_embedding = np.mean(embeddings_array, axis=0)

        if FACE_NORMALIZE_EMBEDDINGS:
            avg_embedding = l2_normalize(avg_embedding)

        face_data = {
            'embeddings': [emb.tolist() for emb in embeddings_array],
            'avg_embedding': avg_embedding.tolist(),
            'count': len(embeddings_array),
            'registered_date': date.today().isoformat()
        }

        employee.face_encoding = pickle.dumps(face_data)
        employee.face_image_path = f"faces/{employee.employee_id}_img1.jpg"
        db.session.commit()

        del temp_embeddings[id]

        # تحديث الذاكرة المؤقتة للمتجهات
        update_embedding_cache(employee.id, employee.face_encoding)

        return jsonify({
            'success': True,
            'message': f'تم تسجيل البصمة بنجاح! ({reg_images} صور)',
            'status': 'completed',
            'count': reg_images
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@face_bp.route('/reset_face_registration/<int:id>', methods=['POST'], endpoint='reset_face_registration')
@login_required(api=True)
def reset_face_registration(id):
    if id in temp_embeddings:
        del temp_embeddings[id]
    return jsonify({'success': True, 'message': 'تم إعادة التعيين'})
