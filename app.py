from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///trip.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

CORS(app)
db = SQLAlchemy(app)

# ==========================================
# 資料庫模型 (Models)
# ==========================================
class Trip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    budget = db.Column(db.Integer, nullable=True)
    
    items = db.relationship('ItineraryItem', backref='trip', lazy=True, cascade="all, delete-orphan")
    expenses = db.relationship('Expense', backref='trip', lazy=True, cascade="all, delete-orphan")

class ItineraryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    day_number = db.Column(db.Integer, nullable=False)
    order_index = db.Column(db.Integer, nullable=False)
    place_name = db.Column(db.String(100), nullable=False)
    start_time = db.Column(db.String(10), nullable=True)
    memo = db.Column(db.Text, nullable=True)

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('itinerary_item.id'), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='JPY')
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(200), nullable=True)

with app.app_context():
    db.create_all()
    # 這裡的預設資料產生器已經移除了！

# ==========================================
# API 路由 (Routes)
# ==========================================

@app.route('/')
def index():
    return jsonify({"message": "API 伺服器運作中！"})

# ----------------- 行程 (Trip) 相關 API -----------------
@app.route('/api/trips', methods=['GET'])
def get_trips():
    trips = Trip.query.all()
    return jsonify([{
        "id": t.id, 
        "title": t.title,
        "start_date": t.start_date.strftime("%Y-%m-%d"), # 轉換成文字格式傳給前端
        "end_date": t.end_date.strftime("%Y-%m-%d")
    } for t in trips])

@app.route('/api/trips', methods=['POST'])
def add_trip():
    data = request.get_json()
    new_trip = Trip(
        title=data.get('title'),
        start_date=datetime.strptime(data.get('start_date'), "%Y-%m-%d").date(),
        end_date=datetime.strptime(data.get('end_date'), "%Y-%m-%d").date(),
        budget=data.get('budget', 0)
    )
    db.session.add(new_trip)
    db.session.commit()
    return jsonify({"status": "success", "id": new_trip.id, "title": new_trip.title}), 201

# ----------------- 景點相關 API -----------------
@app.route('/api/items', methods=['GET'])
def get_items():
    trip_id = request.args.get('trip_id')
    if not trip_id:
        return jsonify([])
    
    items = ItineraryItem.query.filter_by(trip_id=trip_id).order_by(ItineraryItem.order_index).all()
    # 【修改重點】在回傳的資料中，加入 day_number
    result = [{"id": str(item.id), "content": item.place_name, "order_index": item.order_index, "day_number": item.day_number} for item in items]
    return jsonify(result)

@app.route('/api/items', methods=['POST'])
def add_item():
    data = request.get_json()
    new_item = ItineraryItem(
        trip_id=data.get('trip_id'),
        day_number=data.get('day_number', 1), # 【修改重點】從前端接收天數，不再寫死為 1
        order_index=data.get('order_index', 0),
        place_name=data.get('content')
    )
    db.session.add(new_item)
    db.session.commit()
    return jsonify({"status": "success", "id": str(new_item.id)}), 201

@app.route('/api/items/reorder', methods=['PUT'])
def reorder_items():
    data = request.get_json()
    items_data = data.get('reordered_items', [])
    try:
        for item_data in items_data:
            item = ItineraryItem.query.get(int(item_data['id']))
            if item:
                item.order_index = item_data['order_index']
                # 【新增】：如果前端有傳入新的天數，就一併更新
                if 'day_number' in item_data:
                    item.day_number = item_data['day_number']
        db.session.commit()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

# ----------------- 記帳相關 API -----------------
@app.route('/api/expenses', methods=['GET'])
def get_expenses():
    trip_id = request.args.get('trip_id')
    if not trip_id:
        return jsonify([])
    expenses = Expense.query.filter_by(trip_id=trip_id).all()
    result = [{"id": str(exp.id), "amount": exp.amount, "category": exp.category, "description": exp.description, "itemId": str(exp.item_id) if exp.item_id else ""} for exp in expenses]
    return jsonify(result)

@app.route('/api/expenses', methods=['POST'])
def add_expense():
    data = request.get_json()
    item_id = data.get('itemId')
    item_id = int(item_id) if item_id else None

    new_expense = Expense(
        trip_id=data.get('trip_id'), # 改由前端指定行程 ID
        item_id=item_id,
        amount=data.get('amount'),
        category=data.get('category'),
        description=data.get('description')
    )
    db.session.add(new_expense)
    db.session.commit()
    return jsonify({"status": "success", "id": str(new_expense.id)}), 201

if __name__ == '__main__':
    app.run(debug=True, port=5000)