from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime
import os
from werkzeug.utils import secure_filename
import json
from dotenv import load_dotenv
import http.client
import time

# 💡 密碼加密與 JWT 套件
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity

# ====== 💡 新增：用來產生分享安全代碼的加密工具 ======
from itsdangerous import URLSafeTimedSerializer

load_dotenv()

# 新增的 AI 與圖片處理套件
import google.generativeai as genai
from PIL import Image
import io

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 💡 JWT 密鑰設定
app.config['JWT_SECRET_KEY'] = os.environ.get("JWT_SECRET_KEY")
jwt = JWTManager(app)

# ====== 💡 新增：分享連結專用的秘密金鑰與發放工具 ======
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY")
share_serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

CORS(app)
db = SQLAlchemy(app)

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
    except Exception as e:
        print("API 匯率獲取失敗:", e)
        
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

with app.app_context():
    db.create_all()

@app.route('/')
def index():
    return jsonify({"message": "API 伺服器運作中！"})

@app.route('/api/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ====== 🔐 註冊與登入 API ======
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"error": "請提供 Email 與密碼"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "這個 Email 已經註冊過囉！"}), 400

    hashed_password = generate_password_hash(password)
    new_user = User(email=email, password_hash=hashed_password)
    
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"message": "註冊成功！"}), 201

@app.route('/api/login', methods=['POST'])
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

# ====== 🔗 新增：行程分享相關 API ======
@app.route('/api/trips/generate-share', methods=['POST'])
@jwt_required()
def generate_share():
    current_user_id = get_jwt_identity()
    data = request.get_json()
    trip_id = data.get('trip_id')
    role = data.get('role', 'viewer')

    # 安全檢查：確保要求產生連結的人，真的是這個行程的擁有者
    trip = Trip.query.get(trip_id)
    if not trip or str(trip.user_id) != str(current_user_id):
        return jsonify({"error": "找不到行程或您無權分享此行程"}), 403

    # 產生一組加密代碼，把 trip_id 和權限包在裡面
    token = share_serializer.dumps({'trip_id': trip_id, 'role': role})
    
    return jsonify({"share_token": token}), 200

@app.route('/api/trips/accept-share', methods=['POST'])
@jwt_required()
def accept_share():
    current_user_id = get_jwt_identity()
    data = request.get_json()
    token = data.get('share_token')

    try:
        # 解密代碼 (設定有效期限為 7 天：604800 秒)
        payload = share_serializer.loads(token, max_age=604800)
        trip_id = payload['trip_id']
        role = payload['role']
    except Exception as e:
        return jsonify({"error": "分享連結無效或已過期，請重新索取"}), 400

    # 檢查 1：擁有者不能也不需要加入自己的行程
    trip = Trip.query.get(trip_id)
    if not trip:
        return jsonify({"error": "行程已不存在"}), 404
    if str(trip.user_id) == str(current_user_id):
        return jsonify({"message": "這是您自己的行程喔！", "role": "owner"}), 200

    # 檢查 2：是否已經加入過？
    existing_share = TripShare.query.filter_by(trip_id=trip_id, user_id=current_user_id).first()
    if existing_share:
        # 如果擁有者重新給了不同的權限，就幫他更新
        if existing_share.role != role:
            existing_share.role = role
            db.session.commit()
        return jsonify({"message": "您已經在這個行程裡囉！", "role": existing_share.role}), 200

    # 正式加入！將朋友的資料寫進關聯表
    new_share = TripShare(trip_id=trip_id, user_id=current_user_id, role=role)
    db.session.add(new_share)
    db.session.commit()

    return jsonify({"message": "成功加入行程！", "role": role}), 200


# ====== 🤖 AI 掃描發票 API ======
@app.route('/api/scan-receipt', methods=['POST'])
def scan_receipt():
    try:
        if 'receipt_image' not in request.files:
            return jsonify({"error": "沒有圖片"}), 400
            
        file = request.files['receipt_image']
        image_data = file.read()
        image = Image.open(io.BytesIO(image_data))
        
        model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
        
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
        """
        
        response = model.generate_content([prompt, image], generation_config=genai.types.GenerationConfig(response_mime_type="application/json"))
        res_text = response.text.strip()
        print("💡 AI 原始回應:", res_text)
        
        parsed_data = json.loads(res_text)
        return jsonify(parsed_data), 200

    except Exception as e:
        return jsonify({"error": f"後端真實錯誤: {str(e)}"}), 500

# ====== 💡 修改：加上 JWT 警衛，並過濾專屬使用者的行程 ======
@app.route('/api/trips', methods=['GET', 'POST'])
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
        
    # ====== 💡 修改：撈取「自己的」+「別人分享的」行程 ======
    
    # 1. 撈出自己建立的行程
    owned_trips = Trip.query.filter_by(user_id=current_user_id).order_by(Trip.start_date.asc()).all()
    result = []
    for t in owned_trips:
        result.append({
            "id": t.id, 
            "title": t.title, 
            "start_date": t.start_date.strftime("%Y-%m-%d"), 
            "end_date": t.end_date.strftime("%Y-%m-%d"), 
            "budget": t.budget,
            "role": "owner"  # 👑 標記自己是擁有者
        })

    # 2. 撈出別人分享給我的行程
    shared_records = TripShare.query.filter_by(user_id=current_user_id).all()
    for record in shared_records:
        t = Trip.query.get(record.trip_id)
        if t:
            result.append({
                "id": t.id, 
                "title": f"👥 {t.title}", # 加上圖示方便辨識這是共用行程
                "start_date": t.start_date.strftime("%Y-%m-%d"), 
                "end_date": t.end_date.strftime("%Y-%m-%d"), 
                "budget": t.budget,
                "role": record.role  # 📝 標記權限 (editor 或 viewer)
            })

    return jsonify(result), 200

@app.route('/api/trips/<int:trip_id>', methods=['PUT', 'DELETE'])
def modify_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if request.method == 'DELETE':
        db.session.delete(trip)
        db.session.commit()
        return jsonify({"status": "deleted"})
    data = request.get_json()
    trip.title = data.get('title', trip.title)
    if 'start_date' in data: trip.start_date = datetime.strptime(data['start_date'], "%Y-%m-%d").date()
    if 'end_date' in data: trip.end_date = datetime.strptime(data['end_date'], "%Y-%m-%d").date()
    db.session.commit()
    return jsonify({"status": "success"})

@app.route('/api/items', methods=['GET', 'POST'])
def handle_items():
    if request.method == 'POST':
        data = request.get_json()
        new_item = ItineraryItem(trip_id=data.get('trip_id'), day_number=data.get('day_number', 1), order_index=data.get('order_index', 0), place_name=data.get('content'), start_time=data.get('start_time'), memo=data.get('memo'), map_url=data.get('map_url'), category=data.get('category', '景點'))
        db.session.add(new_item)
        db.session.commit()
        return jsonify({"status": "success", "id": str(new_item.id)}), 201
    trip_id = request.args.get('trip_id')
    items = ItineraryItem.query.filter_by(trip_id=trip_id).order_by(ItineraryItem.order_index).all()
    return jsonify([{"id": str(item.id), "content": item.place_name, "order_index": item.order_index, "day_number": item.day_number, "start_time": item.start_time, "memo": item.memo, "map_url": item.map_url, "category": item.category} for item in items])

@app.route('/api/items/<int:item_id>', methods=['PUT', 'DELETE'])
def modify_item(item_id):
    item = ItineraryItem.query.get_or_404(item_id)
    if request.method == 'DELETE':
        db.session.delete(item)
        db.session.commit()
        return jsonify({"status": "deleted"})
    data = request.get_json()
    item.place_name = data.get('content', item.place_name)
    item.start_time = data.get('start_time', item.start_time)
    item.memo = data.get('memo', item.memo)
    item.map_url = data.get('map_url', item.map_url)
    item.category = data.get('category', item.category)
    if 'day_number' in data: item.day_number = data['day_number']
    db.session.commit()
    return jsonify({"status": "success"})

@app.route('/api/items/reorder', methods=['PUT'])
def reorder_items():
    data = request.get_json()
    for item_data in data.get('reordered_items', []):
        item = ItineraryItem.query.get(int(item_data['id']))
        if item:
            item.order_index = item_data['order_index']
            if 'day_number' in item_data: item.day_number = item_data['day_number']
    db.session.commit()
    return jsonify({"status": "success"})

@app.route('/api/expenses', methods=['GET', 'POST'])
def handle_expenses():
    if request.method == 'POST':
        trip_id = request.form.get('trip_id')
        day_number = request.form.get('day_number', 1)
        amount = request.form.get('amount')
        currency = request.form.get('currency', 'JPY')
        category = request.form.get('category')
        description = request.form.get('description')

        image_url = None
        if 'receipt_image' in request.files:
            file = request.files['receipt_image']
            if file.filename != '':
                filename = secure_filename(f"exp_{int(datetime.now().timestamp())}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
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
        return jsonify({"status": "success"}), 201

    trip_id = request.args.get('trip_id')
    expenses = Expense.query.filter_by(trip_id=trip_id).order_by(Expense.id.desc()).all()
    return jsonify([{
        "id": str(exp.id), "amount": exp.amount, "twd_amount": getattr(exp, 'twd_amount', 0), 
        "currency": exp.currency, "category": exp.category, "description": exp.description, 
        "day_number": exp.day_number, "image_url": exp.image_url
    } for exp in expenses])

@app.route('/api/expenses/<int:exp_id>', methods=['PUT', 'DELETE'])
def handle_single_expense(exp_id):
    exp = Expense.query.get_or_404(exp_id)
    if request.method == 'DELETE':
        db.session.delete(exp)
        db.session.commit()
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
    return jsonify({"status": "success"})

@app.route('/api/shopping', methods=['GET', 'POST'])
def handle_shopping():
    if request.method == 'POST':
        trip_id = request.form.get('trip_id')
        name = request.form.get('name')
        location = request.form.get('location', '')
        image_url = None
        if 'item_image' in request.files:
            file = request.files['item_image']
            if file.filename != '':
                filename = secure_filename(f"shop_{int(datetime.now().timestamp())}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_url = f"/api/uploads/{filename}"
        new_shop = ShoppingItem(trip_id=trip_id, name=name, location=location, is_bought=False, image_url=image_url)
        db.session.add(new_shop)
        db.session.commit()
        return jsonify({"status": "success", "id": new_shop.id}), 201

    trip_id = request.args.get('trip_id')
    items = ShoppingItem.query.filter_by(trip_id=trip_id).order_by(ShoppingItem.id).all()
    return jsonify([{"id": str(i.id), "name": i.name, "location": i.location, "is_bought": i.is_bought, "image_url": i.image_url} for i in items])

@app.route('/api/shopping/<int:item_id>', methods=['PUT', 'DELETE'])
def modify_shopping(item_id):
    item = ShoppingItem.query.get_or_404(item_id)
    if request.method == 'DELETE':
        db.session.delete(item)
    else:
        data = request.get_json()
        if 'is_bought' in data: item.is_bought = data['is_bought']
        if 'name' in data: item.name = data['name']
        if 'location' in data: item.location = data['location']
    db.session.commit()
    return jsonify({"status": "success"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5001)