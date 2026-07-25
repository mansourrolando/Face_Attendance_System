# Lazy imports - لا نستورد face_utils مباشرة لأنه يحتاج tensorflow
# بدلاً من ذلك، نستورد فقط ما نحتاجه عند الحاجة
from .csrf import generate_csrf_token, validate_csrf_token
from .rate_limit import login_attempts
from .helpers import log_action, get_setting, _calc_work_hours

# face_utils يتم استيراده فقط من خلال routes التي تحتاجه
# من خلال: from utils.face_utils import ...
