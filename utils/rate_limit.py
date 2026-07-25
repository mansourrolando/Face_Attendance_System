from datetime import datetime

# Rate Limiting - تقييد محاولات تسجيل الدخول
login_attempts = {}  # {client: {'count': N, 'last_attempt': datetime}}

# Rate Limiting على username (يحمي من VPN/IP rotation)
username_attempts = {}  # {username: {'count': N, 'window_start': datetime}}