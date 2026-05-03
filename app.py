from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
# 企業級 PostgreSQL 連線
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
    __tablename__ = 'item' 
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    day_number = db.Column(db.Integer, nullable=False) # 0 代表願望清單
    order_index = db.Column(db.Integer, nullable=False)
    place_name = db.Column(db.String(100), nullable=False)
    start_time = db.Column(db.String(10), nullable=True)
    memo = db.Column(db.Text, nullable=True)
    map_url = db.Column(db.Text, nullable=True)

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

# ----------------- 行程 (Trip) API -----------------
@app.route('/api/trips', methods=['GET', 'POST'])
def handle_trips():
    if request.method == 'POST':
        data = request.get_json()
        budget_val = data.get('budget')
        budget_val = int(budget_val) if budget_val not in ["", None] else 0

        new_trip = Trip(
            title=data.get('title'),
            start_date=datetime.strptime(data.get('start_date'), "%Y-%m-%d").date(),
            end_date=datetime.strptime(data.get('end_date'), "%Y-%m-%d").date(),
            budget=budget_val
        )
        db.session.add(new_trip)
        db.session.commit()
        return jsonify({"status": "success", "id": new_trip.id, "title": new_trip.title}), 201

    trips = Trip.query.all()
    return jsonify([{
        "id": t.id, 
        "title": t.title,
        "start_date": t.start_date.strftime("%Y-%m-%d"),
        "end_date": t.end_date.strftime("%Y-%m-%d"),
        "budget": t.budget
    } for t in trips])

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
    if 'budget' in data: trip.budget = int(data['budget']) if data['budget'] not in ["", None] else 0
    db.session.commit()
    return jsonify({"status": "success"})

# ----------------- 景點 (Item) API -----------------
@app.route('/api/items', methods=['GET', 'POST'])
def handle_items():
    if request.method == 'POST':
        data = request.get_json()
        new_item = ItineraryItem(
            trip_id=data.get('trip_id'),
            day_number=data.get('day_number', 1),
            order_index=data.get('order_index', 0),
            place_name=data.get('content'),
            start_time=data.get('start_time'),
            memo=data.get('memo'),
            map_url=data.get('map_url')
        )
        db.session.add(new_item)
        db.session.commit()
        return jsonify({"status": "success", "id": str(new_item.id)}), 201

    trip_id = request.args.get('trip_id')
    items = ItineraryItem.query.filter_by(trip_id=trip_id).order_by(ItineraryItem.order_index).all()
    result = [{
        "id": str(item.id), 
        "content": item.place_name, 
        "order_index": item.order_index, 
        "day_number": item.day_number, 
        "start_time": item.start_time,
        "memo": item.memo,
        "map_url": item.map_url
    } for item in items]
    return jsonify(result)

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
    if 'day_number' in data: item.day_number = data['day_number']
    db.session.commit()
    return jsonify({"status": "success"})

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

# ----------------- 記帳 (Expense) API -----------------
@app.route('/api/expenses', methods=['GET', 'POST'])
def handle_expenses():
    if request.method == 'POST':
        data = request.get_json()
        item_id = data.get('itemId')
        item_id = int(item_id) if item_id else None
        new_expense = Expense(trip_id=data.get('trip_id'), item_id=item_id, amount=data.get('amount'), category=data.get('category'), description=data.get('description'))
        db.session.add(new_expense)
        db.session.commit()
        return jsonify({"status": "success", "id": str(new_expense.id)}), 201

    trip_id = request.args.get('trip_id')
    expenses = Expense.query.filter_by(trip_id=trip_id).all()
    return jsonify([{"id": str(exp.id), "amount": exp.amount, "category": exp.category, "description": exp.description, "itemId": str(exp.item_id) if exp.item_id else ""} for exp in expenses])

if __name__ == '__main__':
    app.run(debug=True, port=5000)