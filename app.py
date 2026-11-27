import http.client
import ipaddress
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Blueprint, Flask, current_app, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
    verify_jwt_in_request,
)

# ====== 💡 新增：WebSockets 即時通訊套件 ======
from flask_socketio import SocketIO, join_room, leave_room, rooms
from flask_sqlalchemy import SQLAlchemy
from google.api_core.exceptions import GoogleAPIError

# ====== 💡 新增：用來產生分享安全代碼的加密工具 ======
from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

# 💡 密碼加密與 JWT 套件
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

load_dotenv()

# 新增的 AI 與圖片處理套件
import io

import google.generativeai as genai
from PIL import Image

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

api = Blueprint("api", __name__)
db = SQLAlchemy()
jwt = JWTManager()
socketio = SocketIO()
DEFAULT_UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
VALID_SHARE_ROLES = ('viewer', 'editor')


def parse_allowed_origins(value):
    """Parse exact HTTP(S) origins; absent configuration allows no Origin."""
    if value is None:
        return []
    if isinstance(value, str):
        entries = value.split(',')
    elif isinstance(value, (list, tuple)):
        entries = value
    else:
        raise TypeError('ALLOWED_ORIGINS must be a comma-separated string or list')
    result = []
    for item in entries:
        if not isinstance(item, str):
            raise TypeError('Invalid ALLOWED_ORIGINS entry')
        origin = item.strip()
        if not origin:
            continue
        try:
            if not re.fullmatch(r'https?://(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(?::[0-9]+)?', origin):
                raise ValueError
            parsed = urlsplit(origin)
            host = parsed.hostname
            port = parsed.port
            if (parsed.scheme not in ('http', 'https') or not host or parsed.username is not None
                    or parsed.password is not None or parsed.path or parsed.query or parsed.fragment
                    or '?' in origin or '#' in origin or '@' in origin
                    or any(c.isspace() for c in origin) or (port is not None and not 1 <= port <= 65535)):
                raise ValueError
            if ':' in host:
                ipaddress.IPv6Address(host)
            elif not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
                         for label in host.split('.')):
                raise ValueError
            if parsed.netloc.endswith(':') or '*' in origin:
                raise ValueError
        except ValueError as error:
            raise ValueError('Invalid ALLOWED_ORIGINS entry') from error
        if origin not in result:
            result.append(origin)
    return result


def parse_health_check_timeout_seconds(value):
    """Validate a health-check timeout and preserve its decimal precision."""
    try:
        timeout = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(
            'HEALTH_CHECK_TIMEOUT_SECONDS must be between 0 and 30 seconds'
        ) from error
    if not timeout.is_finite() or not Decimal(0) < timeout <= Decimal(30):
        raise ValueError('HEALTH_CHECK_TIMEOUT_SECONDS must be between 0 and 30 seconds')
    return timeout

# ====== 自動匯率 API 與 1小時快取機制 ======
rate_cache = {}

def get_twd_rate(base_currency):
    if base_currency == 'TWD':
        return 1.0

    now = time.time()
    if base_currency in rate_cache and (now - rate_cache[base_currency]['timestamp'] < 3600):
        return rate_cache[base_currency]['rate']

    api_key = os.environ.get("FXRATES_API_KEY")

    try:
        conn = http.client.HTTPSConnection("api.fxratesapi.com")
        url = f"/latest?api_key={api_key}&base={base_currency}&currencies=TWD&resolution=1h&amount=1&places=4&format=json"
        conn.request("GET", url)
        res = conn.getresponse()
        data = res.read()
        parsed = json.loads(data.decode("utf-8"))

        if parsed.get("success") and "rates" in parsed and "TWD" in parsed["rates"]:
            rate = float(parsed["rates"]["TWD"])
            rate_cache[base_currency] = {'rate': rate, 'timestamp': now}
            return rate
    except (
        GoogleAPIError,
        OSError,
        http.client.HTTPException,
        TypeError,
        ValueError,
    ) as error:
        print("API 匯率獲取失敗:", error)

    if base_currency in rate_cache:
        return rate_cache[base_currency]['rate']

    fallbacks = {'JPY': 0.215, 'KRW': 0.024, 'THB': 0.88, 'USD': 32.0, 'EUR': 34.0, 'VND': 0.0013}
    return fallbacks.get(base_currency, 1.0)


# ================= 資料庫模型 =================
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

class Trip(db.Model):
    __tablename__ = 'trip'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    title = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    budget = db.Column(db.Integer, nullable=True)
    items = db.relationship('ItineraryItem', backref='trip', lazy=True, cascade="all, delete-orphan")
    expenses = db.relationship('Expense', backref='trip', lazy=True, cascade="all, delete-orphan")
    shoppings = db.relationship('ShoppingItem', backref='trip', lazy=True, cascade="all, delete-orphan")

class TripShare(db.Model):
    __tablename__ = 'trip_shares'
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='viewer')
    __table_args__ = (db.UniqueConstraint('trip_id', 'user_id', name='_trip_user_uc'),)

class ItineraryItem(db.Model):
    __tablename__ = 'item'
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    day_number = db.Column(db.Integer, nullable=False)
    order_index = db.Column(db.Integer, nullable=False)
    place_name = db.Column(db.String(100), nullable=False)
    start_time = db.Column(db.String(10), nullable=True)
    memo = db.Column(db.Text, nullable=True)
    map_url = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(50), default='景點')

class Expense(db.Model):
    __tablename__ = 'expense'
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=True)
    day_number = db.Column(db.Integer, default=1)
    amount = db.Column(db.Float, nullable=False)
    twd_amount = db.Column(db.Float, default=0)
    currency = db.Column(db.String(10), default='JPY')
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(200), nullable=True)

class ShoppingItem(db.Model):
    __tablename__ = 'shopping_item'
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(100), nullable=True)
    is_bought = db.Column(db.Boolean, default=False)
    image_url = db.Column(db.String(200), nullable=True)

# ================= WebSockets 房間與事件管理 =================

@socketio.on('connect')
def socket_connect(auth):
    sid = request.sid
    app_instance = current_app._get_current_object()
    try:
        token = auth.get('token') if isinstance(auth, dict) else None
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            return False
        with app_instance.test_request_context(headers={'Authorization': f'Bearer {token}'}):
            _, claims = verify_jwt_in_request(locations=['headers'])
            identity = get_jwt_identity()
            if not isinstance(identity, str) or not identity.isascii() or not identity.isdecimal():
                return False
            user_id = int(identity)
            if user_id <= 0 or db.session.get(User, user_id) is None:
                return False
            expiry = claims['exp']
        registry = app_instance.extensions['socket_auth_registry']
        with registry['lock']:
            registry['sids'][sid] = {'user_id': user_id, 'exp': expiry, 'trips': set()}
        socketio.start_background_task(expire_socket, app_instance, sid)
    except Exception:  # noqa: BLE001 -- authentication must fail closed
        registry = app_instance.extensions['socket_auth_registry']
        with registry['lock']:
            registry['sids'].pop(sid, None)
        return False


@socketio.on('disconnect')
def socket_disconnect(reason=None):
    registry = current_app.extensions['socket_auth_registry']
    with registry['lock']:
        registry['sids'].pop(request.sid, None)


def expire_socket(app_instance, sid):
    registry = app_instance.extensions['socket_auth_registry']
    while True:
        with registry['lock']:
            state = registry['sids'].get(sid)
            if state is None:
                return
            remaining = state['exp'] - time.time()
            if remaining <= 0:
                try:
                    socketio.emit('token_expired', {}, to=sid)
                except Exception:  # noqa: BLE001, S110 -- disconnect even if notification fails
                    pass
                try:
                    socketio.server.disconnect(sid, namespace='/')
                except Exception:  # noqa: BLE001, S110 -- fail closed even if transport cleanup fails
                    pass
                finally:
                    registry['sids'].pop(sid, None)
                return
        socketio.sleep(min(remaining, 1))


def cleanup_trip_members(trip_id, user_id=None):
    """Remove affected subscriptions while the registry lock is held."""
    registry = current_app.extensions['socket_auth_registry']
    for sid, state in list(registry['sids'].items()):
        if trip_id not in state['trips'] or (user_id is not None and str(state['user_id']) != str(user_id)):
            continue
        state['trips'].discard(trip_id)
        try:
            socketio.server.leave_room(sid, f'trip_{trip_id}', namespace='/')
        except Exception:  # noqa: BLE001, S110 -- continue cleaning other connections
            pass
        if time.time() < state['exp']:
            try:
                socketio.emit('access_revoked', {'trip_id': trip_id}, to=sid)
            except Exception:  # noqa: BLE001, S110 -- notification must not prevent cleanup
                pass


def emit_trip_update(event, payload, trip_id):
    """Queue protected updates only after checking current access and expiry."""
    trip_id = int(trip_id)
    registry = current_app.extensions['socket_auth_registry']
    with registry['lock']:
        for sid, state in list(registry['sids'].items()):
            if trip_id not in state['trips'] or time.time() >= state['exp']:
                continue
            try:
                db.session.expire_all()
                if not has_trip_access(trip_id, state['user_id']):
                    continue
            except Exception:  # noqa: BLE001 -- never send when access cannot be checked
                db.session.rollback()
                continue
            if time.time() < state['exp']:
                socketio.emit(event, payload, to=sid)


def socket_trip_id(data):
    if not isinstance(data, dict):
        return None
    value = data.get('trip_id')
    if isinstance(value, str):
        if not value.isascii() or not value.isdecimal() or len(value) > 10:
            return None
        value = int(value)
    if type(value) is not int or not 1 <= value <= 2147483647:
        return None
    return value


@socketio.on('join_trip')
def on_join(data=None):
    """當前端進入某個行程分頁時觸發，加入專屬廣播房間"""
    registry = current_app.extensions['socket_auth_registry']
    trip_id = socket_trip_id(data)
    if trip_id is None:
        return {'ok': False, 'error': 'invalid_trip_id'}
    with registry['lock']:
        state = registry['sids'].get(request.sid)
        if state is None or time.time() >= state['exp']:
            return {'ok': False, 'error': 'unauthenticated'}
        try:
            db.session.expire_all()
            if not has_trip_access(trip_id, state['user_id']):
                return {'ok': False, 'error': 'access_denied'}
            if time.time() >= state['exp']:
                return {'ok': False, 'error': 'unauthenticated'}
            room = f"trip_{trip_id}"
            if room not in rooms():
                join_room(room)
            state['trips'].add(trip_id)
        except Exception:  # noqa: BLE001 -- do not authorize when lookup fails
            db.session.rollback()
            return {'ok': False, 'error': 'access_denied'}
    return {'ok': True, 'trip_id': trip_id}

@socketio.on('leave_trip')
def on_leave(data=None):
    """當前端退回大廳時觸發，離開專屬廣播房間"""
    registry = current_app.extensions['socket_auth_registry']
    trip_id = socket_trip_id(data)
    if trip_id is None:
        return {'ok': False, 'error': 'invalid_trip_id'}
    with registry['lock']:
        state = registry['sids'].get(request.sid)
        if state is None:
            return {'ok': False, 'error': 'unauthenticated'}
        leave_room(f"trip_{trip_id}")
        state['trips'].discard(trip_id)
    return {'ok': True, 'trip_id': trip_id}

# ================= API 路由 =================

@api.route('/')
def index():
    return jsonify({"message": "API 伺服器運作中！"})


@api.route('/api/health')
def health():
    """Liveness probe: confirm that the HTTP application can serve a request."""
    return jsonify({"status": "ok"})


@api.route('/api/ready')
def ready():
    """Readiness probe: verify a minimal, read-only database query."""
    try:
        # PostgreSQL's timeout applies only to this transaction. SQLite (used by
        # tests) does not support this setting, so it intentionally skips it.
        if db.session.get_bind().dialect.name == 'postgresql':
            timeout = f"{current_app.config['HEALTH_CHECK_STATEMENT_TIMEOUT_MILLISECONDS']}ms"
            db.session.execute(text("SELECT set_config('statement_timeout', :timeout, true)"),
                               {'timeout': timeout})
        db.session.execute(text('SELECT 1'))
    except SQLAlchemyError:
        # A failed statement leaves a SQLAlchemy session unusable until rollback.
        db.session.rollback()
        return jsonify({"status": "not_ready", "database": "unavailable"}), 503
    return jsonify({"status": "ready", "database": "ok"})


@api.route('/api/uploads/<filename>')
@jwt_required()
def uploaded_file(filename):
    """Serve an upload only to users who can still read its trip."""
    image_url = f"/api/uploads/{filename}"
    trip_ids = {
        trip_id for (trip_id,) in db.session.query(Expense.trip_id).filter_by(image_url=image_url)
    }
    trip_ids.update(
        trip_id for (trip_id,) in db.session.query(ShoppingItem.trip_id).filter_by(image_url=image_url)
    )
    if not trip_ids:
        return jsonify({"error": "圖片不存在"}), 404

    current_user_id = get_jwt_identity()
    if not all(has_trip_access(trip_id, current_user_id) for trip_id in trip_ids):
        return jsonify({"error": "您沒有查看此圖片的權限"}), 403
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)

# ====== 註冊與登入 API ======
@api.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    invite_code = data.get('invite_code')

    if not email or not password:
        return jsonify({"error": "請提供 Email 與密碼"}), 400

    correct_code = os.getenv("INVITE_CODE")

    if invite_code != correct_code:
        return jsonify({"error": "無效的邀請碼"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "這個 Email 已經註冊過囉！"}), 400

    hashed_password = generate_password_hash(password)
    new_user = User(email=email, password_hash=hashed_password)

    db.session.add(new_user)
    db.session.commit()

    return jsonify({"message": "註冊成功！"}), 201

@api.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    user = User.query.filter_by(email=email).first()

    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "帳號或密碼錯誤"}), 401

    access_token = create_access_token(identity=str(user.id))

    return jsonify({
        "message": "登入成功！",
        "access_token": access_token
    }), 200

# ====== 行程分享相關 API ======
@api.route('/api/trips/generate-share', methods=['POST'])
@jwt_required()
def generate_share():
    current_user_id = get_jwt_identity()
    data = request.get_json()
    trip_id = data.get('trip_id')
    role = data.get('role', 'viewer')

    if role not in VALID_SHARE_ROLES:
        return jsonify({"error": "分享角色必須是 viewer 或 editor"}), 400

    trip = Trip.query.get(trip_id)
    if not trip or str(trip.user_id) != str(current_user_id):
        return jsonify({"error": "找不到行程或您無權分享此行程"}), 403

    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    token = serializer.dumps({'trip_id': trip_id, 'role': role})
    return jsonify({"share_token": token}), 200

@api.route('/api/trips/accept-share', methods=['POST'])
@jwt_required()
def accept_share():
    current_user_id = get_jwt_identity()
    data = request.get_json()
    token = data.get('share_token')

    try:
        serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        payload = serializer.loads(token, max_age=604800)
        trip_id = payload['trip_id']
        role = payload['role']
    except (BadData, KeyError, TypeError):
        return jsonify({"error": "分享連結無效或已過期，請重新索取"}), 400

    if role not in VALID_SHARE_ROLES:
        return jsonify({"error": "分享連結角色無效"}), 400

    trip = Trip.query.get(trip_id)
    if not trip:
        return jsonify({"error": "行程已不存在"}), 404
    if str(trip.user_id) == str(current_user_id):
        return jsonify({"message": "這是您自己的行程喔！", "role": "owner"}), 200

    existing_share = TripShare.query.filter_by(trip_id=trip_id, user_id=current_user_id).first()
    if existing_share:
        if existing_share.role != role:
            existing_share.role = role
            db.session.commit()
        return jsonify({"message": "您已經在這個行程裡囉！", "role": existing_share.role}), 200

    new_share = TripShare(trip_id=trip_id, user_id=current_user_id, role=role)
    db.session.add(new_share)
    db.session.commit()

    return jsonify({"message": "成功加入行程！", "role": role}), 200

# ====== 🤖 AI 掃描發票 API ======
@api.route('/api/scan-receipt', methods=['POST'])
@jwt_required()
def scan_receipt():
    try:
        if 'receipt_image' not in request.files:
            return jsonify({"error": "沒有圖片"}), 400

        file = request.files['receipt_image']
        image_data = file.read()
        image = Image.open(io.BytesIO(image_data))

        model = genai.GenerativeModel('gemini-1.5-flash') # 依據你先前的習慣與版本設定

        prompt = """
        你是一個專業的旅遊記帳助手。請分析這張收據照片。
        【⚠️最高強制語言要求】：無論你的伺服器在哪、預設語言為何，或者使用者的手機作業系統語言為何，你「必須、絕對要將所有內容(包含商品名稱、店名等)翻譯成符合台灣人習慣的繁體中文 (Traditional Chinese)」。絕對禁止輸出英文或其他語言！

        請嚴格按照以下 JSON 格式輸出，絕對不可包含 Markdown (如 ```json) 或任何解釋文字：
        {
            "amount": "19153",
            "category": "購物",
            "date": "2026-02-15",
            "receipt_details": {
                "store_name": "店家名稱(必須是繁體中文，可保留原本商標名)",
                "items": [
                    {"name": "樂敦 AG 抗過敏眼藥水 15ml", "qty": 1, "price": 1290},
                    {"name": "OK繃", "qty": 2, "price": 1290}
                ],
                "subtotal": 20162,
                "discount": -1009,
                "total": 19153
            }
        }
        注意規則：
        1. 仔細辨識商品名稱、數量與單價，若無明確數量，qty 預設為 1。
        2. discount 若無折扣則填 0。
        3. amount 必須等於折扣後的 final total (純數字)。
        4. category 只能從 [飲食, 交通, 購物, 住宿, 其他] 中選出最符合的一個。
        5. date 為收據上的消費日期，請一律轉換為 "YYYY-MM-DD" 格式（例如 "2026-02-15"）。若無明確日期請輸出空字串 ""。
        6. 不要出現emoji。
        """

        response = model.generate_content([prompt, image], generation_config=genai.types.GenerationConfig(response_mime_type="application/json"))
        res_text = response.text.strip()
        print("💡 AI 原始回應:", res_text)

        parsed_data = json.loads(res_text)
        return jsonify(parsed_data), 200

    except (AttributeError, GoogleAPIError, OSError, TypeError, ValueError) as error:
        return jsonify({"error": f"後端真實錯誤: {error!s}"}), 500

@api.route('/api/trips', methods=['GET', 'POST'])
@jwt_required()
def handle_trips():
    current_user_id = get_jwt_identity()

    if request.method == 'POST':
        data = request.get_json()
        budget_val = int(data.get('budget')) if data.get('budget') not in ["", None] else 0

        new_trip = Trip(
            user_id=current_user_id,
            title=data.get('title'),
            start_date=datetime.strptime(data.get('start_date'), "%Y-%m-%d").date(),
            end_date=datetime.strptime(data.get('end_date'), "%Y-%m-%d").date(),
            budget=budget_val
        )
        db.session.add(new_trip)
        db.session.commit()
        return jsonify({"status": "success", "id": new_trip.id}), 201

    owned_trips = Trip.query.filter_by(user_id=current_user_id).order_by(Trip.start_date.asc()).all()
    result = []
    for t in owned_trips:
        result.append({
            "id": t.id,
            "title": t.title,
            "start_date": t.start_date.strftime("%Y-%m-%d"),
            "end_date": t.end_date.strftime("%Y-%m-%d"),
            "budget": t.budget,
            "role": "owner"
        })

    shared_records = TripShare.query.filter_by(user_id=current_user_id).all()
    for record in shared_records:
        t = Trip.query.get(record.trip_id)
        if t:
            result.append({
                "id": t.id,
                "title": f"👥 {t.title}",
                "start_date": t.start_date.strftime("%Y-%m-%d"),
                "end_date": t.end_date.strftime("%Y-%m-%d"),
                "budget": t.budget,
                "role": record.role
            })

    return jsonify(result), 200

@api.route('/api/trips/<int:trip_id>', methods=['PUT', 'DELETE'])
@jwt_required()
def modify_trip(trip_id):
    current_user_id = get_jwt_identity()
    if request.method == 'DELETE':
        registry = current_app.extensions['socket_auth_registry']
        with registry['lock']:
            trip = Trip.query.get_or_404(trip_id)
            is_owner = str(trip.user_id) == str(current_user_id)
            share_record = None if is_owner else TripShare.query.filter_by(
                trip_id=trip_id, user_id=current_user_id
            ).first()
            if is_owner:
                db.session.delete(trip)
            elif share_record:
                db.session.delete(share_record)
            else:
                return jsonify({"error": "您無權刪除此行程"}), 403
            db.session.commit()
            cleanup_trip_members(trip_id, None if is_owner else current_user_id)
            return jsonify({"status": "deleted"})
    trip = Trip.query.get_or_404(trip_id)
    is_owner = str(trip.user_id) == str(current_user_id)
    share_record = None
    if not is_owner:
        share_record = TripShare.query.filter_by(
            trip_id=trip_id, user_id=current_user_id
        ).first()

    if not is_owner and (not share_record or share_record.role != 'editor'):
        return jsonify({"error": "您無權修改此行程"}), 403

    data = request.get_json()
    trip.title = data.get('title', trip.title)
    if 'start_date' in data: trip.start_date = datetime.strptime(data['start_date'], "%Y-%m-%d").date()
    if 'end_date' in data: trip.end_date = datetime.strptime(data['end_date'], "%Y-%m-%d").date()
    db.session.commit()
    return jsonify({"status": "success"})


def has_trip_access(trip_id, user_id, require_editor=False):
    """Return whether a user can read or edit data belonging to a trip."""
    try:
        trip_id = int(trip_id)
    except (TypeError, ValueError):
        return False

    trip = db.session.get(Trip, trip_id)
    if not trip:
        return False
    if str(trip.user_id) == str(user_id):
        return True

    share_record = TripShare.query.filter_by(trip_id=trip_id, user_id=user_id).first()
    if not share_record:
        return False
    return not require_editor or share_record.role == 'editor'


@api.route('/api/items', methods=['GET', 'POST'])
@jwt_required()
def handle_items():
    current_user_id = get_jwt_identity()
    if request.method == 'POST':
        data = request.get_json()
        trip_id = data.get('trip_id')
        if not has_trip_access(trip_id, current_user_id, require_editor=True):
            return jsonify({"error": "您無權修改此行程"}), 403
        new_item = ItineraryItem(trip_id=trip_id, day_number=data.get('day_number', 1), order_index=data.get('order_index', 0), place_name=data.get('content'), start_time=data.get('start_time'), memo=data.get('memo'), map_url=data.get('map_url'), category=data.get('category', '景點'))
        db.session.add(new_item)
        db.session.commit()
        # 💡 推播更新給同一行程的人
        emit_trip_update('itinerary_updated', {'action': 'add'}, trip_id)
        return jsonify({"status": "success", "id": str(new_item.id)}), 201

    trip_id = request.args.get('trip_id')
    if not has_trip_access(trip_id, current_user_id):
        return jsonify({"error": "您無權查看此行程"}), 403
    items = ItineraryItem.query.filter_by(trip_id=trip_id).order_by(ItineraryItem.order_index).all()
    return jsonify([{"id": str(item.id), "content": item.place_name, "order_index": item.order_index, "day_number": item.day_number, "start_time": item.start_time, "memo": item.memo, "map_url": item.map_url, "category": item.category} for item in items])

@api.route('/api/items/<int:item_id>', methods=['PUT', 'DELETE'])
@jwt_required()
def modify_item(item_id):
    current_user_id = get_jwt_identity()
    item = ItineraryItem.query.get_or_404(item_id)
    trip_id = item.trip_id
    if not has_trip_access(trip_id, current_user_id, require_editor=True):
        return jsonify({"error": "您無權修改此行程"}), 403
    if request.method == 'DELETE':
        db.session.delete(item)
        db.session.commit()
        # 💡 推播更新
        emit_trip_update('itinerary_updated', {'action': 'delete'}, trip_id)
        return jsonify({"status": "deleted"})

    data = request.get_json()
    item.place_name = data.get('content', item.place_name)
    item.start_time = data.get('start_time', item.start_time)
    item.memo = data.get('memo', item.memo)
    item.map_url = data.get('map_url', item.map_url)
    item.category = data.get('category', item.category)
    if 'day_number' in data: item.day_number = data['day_number']
    db.session.commit()
    # 💡 推播更新
    emit_trip_update('itinerary_updated', {'action': 'update'}, trip_id)
    return jsonify({"status": "success"})

@api.route('/api/items/reorder', methods=['PUT'])
@jwt_required()
def reorder_items():
    current_user_id = get_jwt_identity()
    data = request.get_json()
    reordered_items = data.get('reordered_items', [])
    trip_id = None

    for item_data in reordered_items:
        item = ItineraryItem.query.get(int(item_data['id']))
        if item:
            if not has_trip_access(item.trip_id, current_user_id, require_editor=True):
                return jsonify({"error": "您無權修改此行程"}), 403
            trip_id = item.trip_id # 抓取 trip_id 供推播使用
            item.order_index = item_data['order_index']
            if 'day_number' in item_data: item.day_number = item_data['day_number']

    db.session.commit()
    if trip_id:
        # 💡 推播更新
        emit_trip_update('itinerary_updated', {'action': 'reorder'}, trip_id)
    return jsonify({"status": "success"})

@api.route('/api/expenses', methods=['GET', 'POST'])
@jwt_required()
def handle_expenses():
    current_user_id = get_jwt_identity()
    if request.method == 'POST':
        trip_id = request.form.get('trip_id')
        if not has_trip_access(trip_id, current_user_id, require_editor=True):
            return jsonify({"error": "您無權修改此行程"}), 403
        day_number = request.form.get('day_number', 1)
        amount = request.form.get('amount')
        currency = request.form.get('currency', 'JPY')
        category = request.form.get('category')
        description = request.form.get('description')

        image_url = None
        if 'receipt_image' in request.files:
            file = request.files['receipt_image']
            if file.filename != '':
                filename = secure_filename(f"exp_{uuid.uuid4().hex}_{file.filename}")
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                image_url = f"/api/uploads/{filename}"

        rate = get_twd_rate(currency)
        twd_amount = round(float(amount) * rate)

        new_expense = Expense(
            trip_id=trip_id, item_id=None, day_number=int(day_number),
            amount=float(amount), twd_amount=twd_amount, currency=currency,
            category=category, description=description, image_url=image_url
        )
        db.session.add(new_expense)
        db.session.commit()

        # 💡 推播更新
        emit_trip_update('expenses_updated', {'action': 'add'}, trip_id)
        return jsonify({"status": "success"}), 201

    trip_id = request.args.get('trip_id')
    if not has_trip_access(trip_id, current_user_id):
        return jsonify({"error": "您無權查看此行程"}), 403
    expenses = Expense.query.filter_by(trip_id=trip_id).order_by(Expense.id.desc()).all()
    return jsonify([{
        "id": str(exp.id), "amount": exp.amount, "twd_amount": getattr(exp, 'twd_amount', 0),
        "currency": exp.currency, "category": exp.category, "description": exp.description,
        "day_number": exp.day_number, "image_url": exp.image_url
    } for exp in expenses])

@api.route('/api/expenses/<int:exp_id>', methods=['PUT', 'DELETE'])
@jwt_required()
def handle_single_expense(exp_id):
    current_user_id = get_jwt_identity()
    exp = Expense.query.get_or_404(exp_id)
    trip_id = exp.trip_id
    if not has_trip_access(trip_id, current_user_id, require_editor=True):
        return jsonify({"error": "您無權修改此行程"}), 403

    if request.method == 'DELETE':
        db.session.delete(exp)
        db.session.commit()
        emit_trip_update('expenses_updated', {'action': 'delete'}, trip_id)
        return jsonify({"status": "deleted"})

    data = request.get_json()
    recalculate = False

    if 'amount' in data:
        exp.amount = float(data['amount'])
        recalculate = True
    if 'currency' in data:
        exp.currency = data['currency']
        recalculate = True

    if recalculate:
        rate = get_twd_rate(exp.currency)
        exp.twd_amount = round(exp.amount * rate)

    if 'category' in data: exp.category = data['category']
    if 'description' in data: exp.description = data['description']
    if 'day_number' in data: exp.day_number = int(data['day_number'])

    db.session.commit()
    emit_trip_update('expenses_updated', {'action': 'update'}, trip_id)
    return jsonify({"status": "success"})

@api.route('/api/shopping', methods=['GET', 'POST'])
@jwt_required()
def handle_shopping():
    current_user_id = get_jwt_identity()
    if request.method == 'POST':
        trip_id = request.form.get('trip_id')
        if not has_trip_access(trip_id, current_user_id, require_editor=True):
            return jsonify({"error": "您無權修改此行程"}), 403
        name = request.form.get('name')
        location = request.form.get('location', '')
        image_url = None
        if 'item_image' in request.files:
            file = request.files['item_image']
            if file.filename != '':
                filename = secure_filename(f"shop_{uuid.uuid4().hex}_{file.filename}")
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                image_url = f"/api/uploads/{filename}"
        new_shop = ShoppingItem(trip_id=trip_id, name=name, location=location, is_bought=False, image_url=image_url)
        db.session.add(new_shop)
        db.session.commit()

        emit_trip_update('shopping_updated', {'action': 'add'}, trip_id)
        return jsonify({"status": "success", "id": new_shop.id}), 201

    trip_id = request.args.get('trip_id')
    if not has_trip_access(trip_id, current_user_id):
        return jsonify({"error": "您無權查看此行程"}), 403
    items = ShoppingItem.query.filter_by(trip_id=trip_id).order_by(ShoppingItem.id).all()
    return jsonify([{"id": str(i.id), "name": i.name, "location": i.location, "is_bought": i.is_bought, "image_url": i.image_url} for i in items])

@api.route('/api/shopping/<int:item_id>', methods=['PUT', 'DELETE'])
@jwt_required()
def modify_shopping(item_id):
    current_user_id = get_jwt_identity()
    item = ShoppingItem.query.get_or_404(item_id)
    trip_id = item.trip_id
    if not has_trip_access(trip_id, current_user_id, require_editor=True):
        return jsonify({"error": "您無權修改此行程"}), 403

    if request.method == 'DELETE':
        db.session.delete(item)
    else:
        data = request.get_json()
        if 'is_bought' in data: item.is_bought = data['is_bought']
        if 'name' in data: item.name = data['name']
        if 'location' in data: item.location = data['location']

    db.session.commit()
    emit_trip_update('shopping_updated', {'action': 'update'}, trip_id)
    return jsonify({"status": "success"})


def create_app(test_config=None):
    """Create an application instance with injectable settings for tests."""
    flask_app = Flask(__name__)
    flask_app.extensions['socket_auth_registry'] = {'lock': threading.RLock(), 'sids': {}}
    flask_app.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY=os.environ.get("JWT_SECRET_KEY"),
        SECRET_KEY=os.environ.get("SECRET_KEY", "fallback_secret_key"),
        UPLOAD_FOLDER=DEFAULT_UPLOAD_FOLDER,
        SOCKETIO_ASYNC_MODE=os.environ.get('SOCKETIO_ASYNC_MODE', 'threading'),
        ALLOWED_ORIGINS=os.environ.get('ALLOWED_ORIGINS'),
        HEALTH_CHECK_TIMEOUT_SECONDS=os.environ.get('HEALTH_CHECK_TIMEOUT_SECONDS', '5'),
    )

    if test_config:
        flask_app.config.update(test_config)

    health_timeout = parse_health_check_timeout_seconds(
        flask_app.config['HEALTH_CHECK_TIMEOUT_SECONDS']
    )
    flask_app.config['HEALTH_CHECK_TIMEOUT_SECONDS'] = float(health_timeout)
    flask_app.config['HEALTH_CHECK_STATEMENT_TIMEOUT_MILLISECONDS'] = int(
        (health_timeout * 1000).to_integral_value(rounding=ROUND_CEILING)
    )
    database_uri = flask_app.config['SQLALCHEMY_DATABASE_URI']
    if isinstance(database_uri, str) and database_uri.startswith('postgresql'):
        flask_app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            # libpq/psycopg2 only accepts an integer number of seconds here.
            # Round positive fractional values up so they never disable the timeout.
            'connect_args': {
                'connect_timeout': int(
                    health_timeout.to_integral_value(rounding=ROUND_CEILING)
                )
            },
        }

    async_mode = flask_app.config['SOCKETIO_ASYNC_MODE']
    if async_mode not in ('threading', 'gevent', 'eventlet'):
        raise ValueError(
            "SOCKETIO_ASYNC_MODE must be one of: threading, gevent, eventlet"
        )

    allowed_origins = parse_allowed_origins(flask_app.config['ALLOWED_ORIGINS'])
    flask_app.config['ALLOWED_ORIGINS'] = allowed_origins
    os.makedirs(flask_app.config['UPLOAD_FOLDER'], exist_ok=True)
    CORS(flask_app, origins=[re.compile('^' + re.escape(origin) + '$') for origin in allowed_origins],
         always_send=False, supports_credentials=False, vary_header=True)
    db.init_app(flask_app)
    jwt.init_app(flask_app)
    try:
        socketio.init_app(
            flask_app,
            cors_allowed_origins=lambda origin: origin in allowed_origins,
            cors_credentials=False,
            async_mode=async_mode,
        )
    except (ValueError, ImportError) as error:
        raise RuntimeError(
            f"Cannot initialize Socket.IO async mode '{async_mode}'; "
            "verify its dependencies are installed."
        ) from error
    socket_wsgi_app = flask_app.wsgi_app

    def reject_empty_socket_origin(environ, start_response):
        # Engine.IO treats an empty Origin as if the header were absent.
        if (environ.get('PATH_INFO', '').rstrip('/') == '/socket.io'
                and environ.get('HTTP_ORIGIN') == ''):
            start_response('403 Forbidden', [('Content-Type', 'text/plain'), ('Content-Length', '0')])
            return [b'']
        return socket_wsgi_app(environ, start_response)

    flask_app.wsgi_app = reject_empty_socket_origin
    flask_app.register_blueprint(api)
    return flask_app


app = create_app()

if __name__ == '__main__':
    # 💡 啟動時改用 socketio.run 來驅動 Flask 伺服器
    with app.app_context():
        db.create_all()
    socketio.run(app, host='0.0.0.0', debug=True, port=5001)
