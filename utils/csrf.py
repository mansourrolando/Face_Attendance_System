import hashlib
import uuid
from flask import session


def generate_csrf_token():
    """توليد رمز CSRF وحفظه في الجلسة"""
    if '_csrf_token' not in session:
        session['_csrf_token'] = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    return session['_csrf_token']


def validate_csrf_token(token):
    """التحقق من رمز CSRF"""
    return token and token == session.get('_csrf_token')
