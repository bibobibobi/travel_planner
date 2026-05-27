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

# 💡 新增：密碼加密與 JWT 套件
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity

load_dotenv()

# 新增的 AI 與圖片處理套件
import google.generativeai as genai
from PIL import Image
import io

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://travel_user:travel123@localhost/travel_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 💡 新增：JWT 密鑰設定 (建議未來把這串金鑰放到 .env 檔案裡)
app.config['JWT_SECRET_KEY'] = os.environ.get("JWT_SECRET_KEY", "your-super-secret-key-change-me-later")
jwt = JWTManager(app)

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

CORS(app)
db = SQLAlchemy(app)

# ====== 💡 自動匯率 API 與 1小時快取機制 ======
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

# 💡 新增：使用者資料表
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

class Trip(db.Model):
    __tablename__ = 'trip'
    id = db.Column(db.Integer, primary_key=True)
    # 💡 新增：記錄這個行程是哪個使用者創建的 (設為 nullable=True 是為了不讓你原本舊的假資料壞掉)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) 
    title = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    budget = db.Column(db.Integer, nullable=True)
    items = db.relationship('ItineraryItem', backref='trip', lazy=True, cascade="all, delete-orphan")
    expenses = db.relationship('Expense', backref='trip', lazy=True, cascade="all, delete-orphan")
    shoppings = db.relationship('ShoppingItem', backref='trip', lazy=True, cascade="all, delete-orphan")

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

# ====== 🔐 新增：註冊與登入 API ======
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

    # 登入成功，將使用者的 ID 包裝進 JWT Token 中發放
    access_token = create_access_token(identity=str(user.id))
    
    return jsonify({
        "message": "登入成功！",
        "access_token": access_token
    }), 200

# ====== 🤖 核心功能：AI 掃描發票 API ======
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

# --- 其餘 API 路由 ---
# ====== 💡 修改：加上 JWT 警衛，並過濾專屬使用者的行程 ======
@app.route('/api/trips', methods=['GET', 'POST'])
@jwt_required() # 💂‍♂️ 警衛在這裡！沒有帶 Token 的請求會直接被踢出去
def handle_trips():
    # 取得當前拿著這張 Token 登入的使用者 ID
    current_user_id = get_jwt_identity() 

    if request.method == 'POST':
        data = request.get_json()
        budget_val = int(data.get('budget')) if data.get('budget') not in ["", None] else 0
        
        # 💡 新增時，把 user_id 烙印在這個行程上
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
        
    # 💡 查詢時，只撈取「擁有者是自己」的行程，不再是 query.all() 了！
    user_trips = Trip.query.filter_by(user_id=current_user_id).all()
    
    return jsonify([{
        "id": t.id, 
        "title": t.title, 
        "start_date": t.start_date.strftime("%Y-%m-%d"), 
        "end_date": t.end_date.strftime("%Y-%m-%d"), 
        "budget": t.budget
    } for t in user_trips])

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
    app.run(debug=True, port=5000)