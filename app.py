from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://travel_user:travel123@localhost/travel_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

CORS(app)
db = SQLAlchemy(app)

class Trip(db.Model):
    __tablename__ = 'trip'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    budget = db.Column(db.Integer, nullable=True)

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

@app.route('/')
def index():
    return jsonify({"message": "API 伺服器運作中！"})

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
        "id": t.id, "title": t.title, "start_date": t.start_date.strftime("%Y-%m-%d"),
        "end_date": t.end_date.strftime("%Y-%m-%d"), "budget": t.budget
    } for t in trips])

@app.route('/api/trips/<int:trip_id>', methods=['PUT', 'DELETE'])
def modify_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if request.method == 'DELETE':
        # 連帶刪除該行程的所有景點與記帳 (Cascade 處理)
        Expense.query.filter_by(trip_id=trip_id).delete()
        ItineraryItem.query.filter_by(trip_id=trip_id).delete()
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

@app.route('/api/items', methods=['GET', 'POST'])
def handle_items():
    if request.method == 'POST':
        data = request.get_json()
        new_item = ItineraryItem(
            trip_id=data.get('trip_id'), day_number=data.get('day_number', 1),
            order_index=data.get('order_index', 0), place_name=data.get('content'),
            start_time=data.get('start_time'), memo=data.get('memo'), map_url=data.get('map_url')
        )
        db.session.add(new_item)
        db.session.commit()
        return jsonify({"status": "success", "id": str(new_item.id)}), 201

    trip_id = request.args.get('trip_id')
    items = ItineraryItem.query.filter_by(trip_id=trip_id).order_by(ItineraryItem.order_index).all()
    return jsonify([{
        "id": str(item.id), "content": item.place_name, "order_index": item.order_index, 
        "day_number": item.day_number, "start_time": item.start_time, "memo": item.memo, "map_url": item.map_url
    } for item in items])

@app.route('/api/items/<int:item_id>', methods=['PUT', 'DELETE'])
def modify_item(item_id):
    item = ItineraryItem.query.get_or_404(item_id)
    if request.method == 'DELETE':
        # 解除綁定：把有綁定這個景點的記帳，設為沒有綁定 (None) 以免報錯
        Expense.query.filter_by(item_id=item_id).update({'item_id': None})
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
        data = request.get_json()
        item_id = int(data.get('itemId')) if data.get('itemId') else None
        new_expense = Expense(trip_id=data.get('trip_id'), item_id=item_id, amount=data.get('amount'), category=data.get('category'), description=data.get('description'))
        db.session.add(new_expense)
        db.session.commit()
        return jsonify({"status": "success"}), 201
    trip_id = request.args.get('trip_id')
    expenses = Expense.query.filter_by(trip_id=trip_id).all()
    return jsonify([{"id": str(exp.id), "amount": exp.amount, "category": exp.category, "description": exp.description, "itemId": str(exp.item_id) if exp.item_id else ""} for exp in expenses])

# 新增：刪除單筆記帳
@app.route('/api/expenses/<int:exp_id>', methods=['DELETE'])
def delete_expense(exp_id):
    exp = Expense.query.get_or_404(exp_id)
    db.session.delete(exp)
    db.session.commit()
    return jsonify({"status": "deleted"})

if __name__ == '__main__':
    app.run(debug=True, port=5000)