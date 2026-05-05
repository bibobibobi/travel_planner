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

# ====== 🤖 核心功能：AI 掃描發票 API ======
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
        
        # 給 AI 的嚴格且聰明的指令 (解除字數限制版)
        prompt = """
        你是一個專業的旅遊記帳助手。請看這張發票或收據的照片，並找出以下資訊：
        1. 最終結帳的「總金額」(只要純數字，排除稅額計算的過程，抓取最終付款總額)。
        2. 「消費明細」：請先寫出【店家名稱】，接著用破折號加上【代表性的商品清單】(盡量列出完整品項，字數不限)。
           【翻譯與保留規則】：請以「繁體中文」輸出。但特定的品牌、店名、或日本漢字商品名（如：松本清、唐吉訶德、休足時間、雪肌精等）請「保留原文」不翻譯。一般物品才翻譯。
           (範例："MEGA 唐吉訶德 - 休足時間、洗面乳、抹茶巧克力、綠茶、塑膠袋")
        3. 「消費類別」，只能根據這張發票的"主要"屬性，從這五個嚴格選一個：飲食、交通、購物、住宿、其他。

        請嚴格只回傳 JSON 格式，不要有任何多餘的引言或 markdown 符號。
        格式範例：
        {"amount": "5400", "description": "松本清 - 合利他命、雪肌精化妝水、感冒藥、護唇膏、棉花棒", "category": "購物"}
        """
        
        response = model.generate_content([prompt, image])
        res_text = response.text.strip()
        
        # 清理可能帶有的 Markdown 標記 (Gemini有時會雞婆加上 ```json )
        if res_text.startswith('```json'):
            res_text = res_text[7:-3].strip()
        elif res_text.startswith('```'):
            res_text = res_text[3:-3].strip()
            
        # 轉成 Python 字典並回傳給前端
        parsed_data = json.loads(res_text)
        return jsonify(parsed_data), 200

    except Exception as e:
        print("AI 辨識錯誤:", str(e))
        return jsonify({"error": "無法辨識圖片，請手動輸入"}), 500

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