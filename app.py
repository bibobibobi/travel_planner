from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime
import os
from werkzeug.utils import secure_filename
import json
from dotenv import load_dotenv
load_dotenv()

import google.generativeai as genai
from PIL import Image
import io

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://travel_user:travel123@localhost/travel_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

CORS(app)
db = SQLAlchemy(app)

# ================= 資料庫模型 =================
class Trip(db.Model):
    __tablename__ = 'trip'
    id = db.Column(db.Integer, primary_key=True)
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
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=True) # 保留舊欄位防報錯
    day_number = db.Column(db.Integer, default=1) # 💡 新增的：記錄這筆帳是第幾天
    amount = db.Column(db.Float, nullable=False)
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

# ====== 🤖 核心功能：AI 掃描發票 API (進階明細解析版) ======
@app.route('/api/scan-receipt', methods=['POST'])
def scan_receipt():
    try:
        if 'receipt_image' not in request.files:
            return jsonify({"error": "沒有圖片"}), 400
            
        file = request.files['receipt_image']
        image_data = file.read()
        image = Image.open(io.BytesIO(image_data))
        
        model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
        
        # 給 AI 的嚴格指令 (專治外文翻譯與價格提取，強制鎖死繁體中文)
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
        
        response = model.generate_content(
            [prompt, image],
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
            )
        )
        
        res_text = response.text.strip()
        print("💡 AI 原始回應:", res_text)
        
        parsed_data = json.loads(res_text)
        return jsonify(parsed_data), 200

    except json.JSONDecodeError as je:
        print("❌ JSON 解析錯誤:", str(je), "原始文字:", res_text)
        return jsonify({"error": "AI 回傳格式異常，請重拍一次"}), 500
    except Exception as e:
        import sys
        import traceback
        print("❌ 真實死因:", str(e), flush=True)
        print(traceback.format_exc(), flush=True)
        sys.stdout.flush()
        return jsonify({"error": f"後端真實錯誤: {str(e)}"}), 500

# --- 其餘既有的 API 路由保持完全不變 ---
@app.route('/api/trips', methods=['GET', 'POST'])
def handle_trips():
    if request.method == 'POST':
        data = request.get_json()
        budget_val = int(data.get('budget')) if data.get('budget') not in ["", None] else 0
        new_trip = Trip(title=data.get('title'), start_date=datetime.strptime(data.get('start_date'), "%Y-%m-%d").date(), end_date=datetime.strptime(data.get('end_date'), "%Y-%m-%d").date(), budget=budget_val)
        db.session.add(new_trip)
        db.session.commit()
        return jsonify({"status": "success", "id": new_trip.id}), 201
    return jsonify([{"id": t.id, "title": t.title, "start_date": t.start_date.strftime("%Y-%m-%d"), "end_date": t.end_date.strftime("%Y-%m-%d"), "budget": t.budget} for t in Trip.query.all()])

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
        Expense.query.filter_by(item_id=item_id).update({'item_id': None})
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
        category = request.form.get('category')
        description = request.form.get('description')

        image_url = None
        if 'receipt_image' in request.files:
            file = request.files['receipt_image']
            if file.filename != '':
                filename = secure_filename(f"exp_{int(datetime.now().timestamp())}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_url = f"/api/uploads/{filename}"

        # 💡 將 item_id 設為 None，改用 day_number 記錄
        new_expense = Expense(trip_id=trip_id, item_id=None, day_number=int(day_number), amount=float(amount), category=category, description=description, image_url=image_url)
        db.session.add(new_expense)
        db.session.commit()
        return jsonify({"status": "success"}), 201

    trip_id = request.args.get('trip_id')
    expenses = Expense.query.filter_by(trip_id=trip_id).order_by(Expense.id.desc()).all()
    # 💡 GET 回傳時加上 day_number
    return jsonify([{"id": str(exp.id), "amount": exp.amount, "category": exp.category, "description": exp.description, "day_number": exp.day_number, "image_url": exp.image_url} for exp in expenses])

@app.route('/api/expenses/<int:exp_id>', methods=['PUT', 'DELETE'])
def handle_single_expense(exp_id):
    exp = Expense.query.get_or_404(exp_id)
    if request.method == 'DELETE':
        db.session.delete(exp)
        db.session.commit()
        return jsonify({"status": "deleted"})
    
    data = request.get_json()
    if 'amount' in data: exp.amount = float(data['amount'])
    if 'category' in data: exp.category = data['category']
    if 'description' in data: exp.description = data['description']
    if 'day_number' in data: exp.day_number = int(data['day_number']) # 💡 支援編輯修改天數
    
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