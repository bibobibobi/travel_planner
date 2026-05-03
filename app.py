from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
# 替換為正式的 PostgreSQL 連線
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://travel_user:travel123@localhost/travel_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

CORS(app)
db = SQLAlchemy(app)

# ==========================================
# 資料庫模型 (Models)
# ==========================================
class Trip(db.Model):
    __tablename__ = 'trip'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    budget = db.Column(db.Integer, nullable=True)
    
    items = db.relationship('ItineraryItem', backref='trip', lazy=True, cascade="all, delete-orphan")
    expenses = db.relationship('Expense', backref='trip', lazy=True, cascade="all, delete-orphan")

class ItineraryItem(db.Model):
    __tablename__ = 'item' # 強制對應我們剛剛在資料庫改名的 item 表
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    day_number = db.Column(db.Integer, nullable=False)
    order_index = db.Column(db.Integer, nullable=False)
    place_name = db.Column(db.String(100), nullable=False)
    start_time = db.Column(db.String(10), nullable=True)
    memo = db.Column(db.Text, nullable=True)
    map_url = db.Column(db.Text, nullable=True) # 新增的地圖連結欄位

class Expense(db.Model):
    __tablename__ = 'expense'
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='JPY')
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(200), nullable=True)

with app.app_context():
    db.create_all()

# ==========================================
# API 路由 (Routes)
# ==========================================

@app.route('/')
def index():
    return jsonify({"message": "API 伺服器運作中！"})

@app.route('/api/trips', methods=['GET'])
def get_trips():
    trips = Trip.query.all()
    return jsonify([{
        "id": t.id, 
        "title": t.title,
        "start_date": t.start_date.strftime("%Y-%m-%d"),
        "end_date": t.end_date.strftime("%Y-%m-%d")
    } for t in trips])

@app.route('/api/trips', methods=['POST'])
def add_trip():
    data = request.get_json()
    budget_val = data.get('budget')
    # 防呆：避免空字串寫入 Integer 欄位報錯
    if budget_val == "" or budget_val is None:
        budget_val = 0
    else:
        budget_val = int(budget_val)

    new_trip = Trip(
        title=data.get('title'),
        start_date=datetime.strptime(data.get('start_date'), "%Y-%m-%d").date(),
        end_date=datetime.strptime(data.get('end_date'), "%Y-%m-%d").date(),
        budget=budget_val
    )
    db.session.add(new_trip)
    db.session.commit()
    return jsonify({"status": "success", "id": new_trip.id, "title": new_trip.title}), 201

@app.route('/api/items', methods=['GET'])
def get_items():
    trip_id = request.args.get('trip_id')
    if not trip_id:
        return jsonify([])
    
    items = ItineraryItem.query.filter_by(trip_id=trip_id).order_by(ItineraryItem.order_index).all()
    result = [{"id": str(item.id), "content": item.place_name, "order_index": item.order_index, "day_number": item.day_number, "map_url": item.map_url} for item in items]
    return jsonify(result)

@app.route('/api/items', methods=['POST'])
def add_item():
    data = request.get_json()
    new_item = ItineraryItem(
        trip_id=data.get('trip_id'),
        day_number=data.get('day_number', 1),
        order_index=data.get('order_index', 0),
        place_name=data.get('content'),
        map_url=data.get('map_url') # 接收前端傳來的地圖連結
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
                if 'day_number' in item_data:
                    item.day_number = item_data['day_number']
        db.session.commit()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

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
        trip_id=data.get('trip_id'),
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