from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime
import os
from werkzeug.utils import secure_filename
import json
from dotenv import load_dotenv
load_dotenv()

# 新增的 AI 與圖片處理套件
import google.generativeai as genai
from PIL import Image
import io

# 💡 填入你的 Gemini API 金鑰
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
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='JPY')
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(200), nullable=True)
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

# ====== 🤖 核心功能：AI 掃描發票 API (高精準穩定版) ======
@app.route('/api/scan-receipt', methods=['POST'])
def scan_receipt():
    try:
        if 'receipt_image' not in request.files:
            return jsonify({"error": "沒有圖片"}), 400
            
        file = request.files['receipt_image']
        
        # 在記憶體中打開圖片，不存進硬碟
        image_data = file.read()
        image = Image.open(io.BytesIO(image_data))
        
        # 呼叫 Gemini 模型
        model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
        
        # 給 AI 的嚴格指令 (專治複雜格式與多國語言發票)
        prompt = """
        你是一個專業的旅遊記帳助手。請分析這張收據照片，提取以下3個資訊：
        1. "amount": 最終付款「總金額」(請移除千位數逗號，只要純數字字串，例如 "1139")。請特別注意發票上的「合計」、「支払」或折扣後的最終實際支付金額。
        2. "description": 「消費明細」(格式：【店家名稱】 - 【商品清單】)。請將商品翻譯為繁體中文，但品牌或專有名詞(如 セブン-イレブン, nanaco)保留原文。請將所有品項串接在同一行，絕對「不可使用換行符號」。
        3. "category": 「消費類別」，只能從 [飲食, 交通, 購物, 住宿, 其他] 中選出一個最主要的屬性。

        請務必遵守：只輸出標準 JSON 格式，不可包含 Markdown 標記，不可包含任何解釋文字。
        格式範例:{"amount": "5400", "description": "松本清 - 合利他命、雪肌精化妝水、感冒藥、護唇膏、棉花棒", "category": "購物"}
        """
        
        # 💡 殺手鐧：強制模型只能在底層輸出 JSON 格式，徹底杜絕字串解析崩潰
        response = model.generate_content(
            [prompt, image],
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
            )
        )
        
        res_text = response.text.strip()
        print("💡 AI 原始回應:", res_text) # 印出日誌，方便你在伺服器上查看辨識細節
        
        # 直接轉成 Python 字典，不再需要手動清理 ```json
        parsed_data = json.loads(res_text)
        return jsonify(parsed_data), 200

    except json.JSONDecodeError as je:
        print("❌ JSON 解析錯誤:", str(je), "原始文字:", res_text)
        return jsonify({"error": "AI 回傳格式異常，請重拍一次"}), 500
    except Exception as e:
        # 💡 強制清除緩衝，印出到伺服器日誌
        import sys
        import traceback
        print("❌ 真實死因:", str(e), flush=True)
        print(traceback.format_exc(), flush=True)
        sys.stdout.flush()
        
        # 💡 【關鍵】把真正的錯誤訊息直接包成 JSON 傳給前端！
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
        item_id = request.form.get('itemId')
        item_id = int(item_id) if item_id else None
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

        new_expense = Expense(trip_id=trip_id, item_id=item_id, amount=float(amount), category=category, description=description, image_url=image_url)
        db.session.add(new_expense)
        db.session.commit()
        return jsonify({"status": "success"}), 201

    trip_id = request.args.get('trip_id')
    expenses = Expense.query.filter_by(trip_id=trip_id).all()
    return jsonify([{"id": str(exp.id), "amount": exp.amount, "category": exp.category, "description": exp.description, "itemId": str(exp.item_id) if exp.item_id else "", "image_url": exp.image_url} for exp in expenses])

# --- 記帳 API (支援 刪除 與 編輯更新) ---
@app.route('/api/expenses/<int:exp_id>', methods=['PUT', 'DELETE'])
def handle_single_expense(exp_id):
    exp = Expense.query.get_or_404(exp_id)
    if request.method == 'DELETE':
        db.session.delete(exp)
        db.session.commit()
        return jsonify({"status": "deleted"})
    
    # 💡 這裡是補上的編輯邏輯
    data = request.get_json()
    if 'amount' in data: exp.amount = float(data['amount'])
    if 'category' in data: exp.category = data['category']
    if 'description' in data: exp.description = data['description']
    if 'itemId' in data: exp.item_id = int(data['itemId']) if data['itemId'] else None
    
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