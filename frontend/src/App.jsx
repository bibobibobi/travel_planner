import { useState, useEffect } from 'react'
import { DragDropContext, Droppable, Draggable } from '@hello-pangea/dnd'
import './App.css'

const API_BASE = '/api'

function App() {
  const [trips, setTrips] = useState([])
  const [currentTrip, setCurrentTrip] = useState(null)
  const [isEditingTrip, setIsEditingTrip] = useState(false)
  const [editTripForm, setEditTripForm] = useState({})

  const [newTripForm, setNewTripForm] = useState({ title: '', start_date: '', end_date: '', budget: '' })

  const [activeTab, setActiveTab] = useState('itinerary') // 'itinerary', 'wishlist', 'expenses'
  const [selectedDay, setSelectedDay] = useState(1)

  const [items, setItems] = useState([])
  const [editingItemId, setEditingItemId] = useState(null)
  const [editItemForm, setEditItemForm] = useState({})

  const [newItemForm, setNewItemForm] = useState({ content: '', start_time: '', map_url: '', memo: '' })

  const [expenses, setExpenses] = useState([])
  const [newExpense, setNewExpense] = useState({ amount: '', category: '飲食', description: '', itemId: '' })

  const getTripDays = (start, end) => {
    const d1 = new Date(start)
    const d2 = new Date(end)
    const diffTime = Math.abs(d2 - d1)
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) + 1
    return diffDays > 0 ? diffDays : 1
  }

  const totalDays = currentTrip ? getTripDays(currentTrip.start_date, currentTrip.end_date) : 1

  const getDisplayDate = (startDate, dayNumber) => {
    if (!startDate || dayNumber === 0) return '';
    const date = new Date(startDate + 'T00:00:00');
    date.setDate(date.getDate() + dayNumber - 1);
    return `${date.getMonth() + 1}/${date.getDate()}`;
  }

  useEffect(() => { fetchTrips() }, [])
  const fetchTrips = () => { fetch(`${API_BASE}/trips`).then(res => res.json()).then(setTrips) }
  const selectTrip = (trip) => { setCurrentTrip(trip); setSelectedDay(1); fetchItems(trip.id); fetchExpenses(trip.id); setIsEditingTrip(false); }
  const fetchItems = (tripId) => { fetch(`${API_BASE}/items?trip_id=${tripId}`).then(res => res.json()).then(setItems) }
  const fetchExpenses = (tripId) => { fetch(`${API_BASE}/expenses?trip_id=${tripId}`).then(res => res.json()).then(setExpenses) }

  // --- 旅遊行程操作 ---
  const handleCreateTrip = (e) => {
    e.preventDefault()
    fetch(`${API_BASE}/trips`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newTripForm) })
      .then(() => { fetchTrips(); setNewTripForm({ title: '', start_date: '', end_date: '', budget: '' }) })
  }

  const handleUpdateTrip = (e) => {
    e.preventDefault()
    fetch(`${API_BASE}/trips/${currentTrip.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(editTripForm) })
      .then(() => {
        setCurrentTrip({ ...currentTrip, ...editTripForm });
        fetchTrips();
        setIsEditingTrip(false);
      })
  }

  // --- 景點操作 ---
  const handleAddItem = (e) => {
    e.preventDefault()
    if (!newItemForm.content) return
    const targetDay = activeTab === 'wishlist' ? 0 : selectedDay;
    const orderIndex = items.filter(i => i.day_number === targetDay).length;

    fetch(`${API_BASE}/items`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trip_id: currentTrip.id, day_number: targetDay, order_index: orderIndex, ...newItemForm })
    }).then(() => {
      fetchItems(currentTrip.id);
      setNewItemForm({ content: '', start_time: '', map_url: '', memo: '' });
    })
  }

  const startEditingItem = (item) => {
    setEditingItemId(item.id)
    setEditItemForm(item)
  }

  const saveEditedItem = () => {
    fetch(`${API_BASE}/items/${editingItemId}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(editItemForm)
    }).then(() => {
      fetchItems(currentTrip.id)
      setEditingItemId(null)
    })
  }

  const deleteItem = (id) => {
    if (window.confirm("確定要刪除這個景點嗎？")) {
      fetch(`${API_BASE}/items/${id}`, { method: 'DELETE' }).then(() => fetchItems(currentTrip.id))
    }
  }

  // --- 記帳操作 ---
  const handleAddExpense = (e) => {
    e.preventDefault()
    if (!newExpense.amount) return
    fetch(`${API_BASE}/expenses`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trip_id: currentTrip.id, itemId: newExpense.itemId, amount: parseFloat(newExpense.amount), category: newExpense.category, description: newExpense.description })
    }).then(() => { fetchExpenses(currentTrip.id); setNewExpense({ amount: '', category: '飲食', description: '', itemId: '' }) })
  }

  const totalExpense = expenses.reduce((sum, exp) => sum + exp.amount, 0)

  // --- 拖曳邏輯 ---
  const onDragEnd = (result) => {
    const { source, destination } = result;
    if (!destination) return;

    const sourceDay = parseInt(source.droppableId.split('-')[1]);
    const destDay = parseInt(destination.droppableId.split('-')[1]);
    let newItems = Array.from(items);

    const sourceItems = newItems.filter(i => i.day_number === sourceDay).sort((a, b) => a.order_index - b.order_index);
    const destItems = sourceDay === destDay ? sourceItems : newItems.filter(i => i.day_number === destDay).sort((a, b) => a.order_index - b.order_index);

    const [draggedItem] = sourceItems.splice(source.index, 1);
    draggedItem.day_number = destDay;
    destItems.splice(destination.index, 0, draggedItem);

    const updatedSourceItems = sourceItems.map((item, index) => ({ ...item, order_index: index }));
    const updatedDestItems = sourceDay === destDay ? updatedSourceItems : destItems.map((item, index) => ({ ...item, order_index: index }));

    const payload = sourceDay === destDay
      ? updatedSourceItems.map(item => ({ id: item.id, order_index: item.order_index, day_number: sourceDay }))
      : [
        ...updatedSourceItems.map(item => ({ id: item.id, order_index: item.order_index, day_number: sourceDay })),
        ...updatedDestItems.map(item => ({ id: item.id, order_index: item.order_index, day_number: destDay }))
      ];

    // 樂觀更新 UI
    newItems = newItems.map(item => {
      const up = payload.find(p => p.id === item.id);
      return up ? { ...item, ...up } : item;
    });
    setItems(newItems);

    fetch(`${API_BASE}/items/reorder`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reordered_items: payload }) });
  }

  // ================= 畫面渲染：大廳 =================
  if (!currentTrip) {
    return (
      <div style={{ minHeight: '100vh', backgroundColor: '#f0f4f8', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px', fontFamily: '"Segoe UI", Tahoma, Geneva, Verdana, sans-serif' }}>
        <div style={{ width: '100%', maxWidth: '600px', backgroundColor: '#ffffff', padding: '30px', borderRadius: '16px', boxShadow: '0 10px 30px rgba(0,0,0,0.05)' }}>
          <h1 style={{ textAlign: 'center', color: '#1a365d', marginBottom: '30px', fontSize: '1.8em' }}>✈️ 我的旅遊管理大廳</h1>
          <div style={{ backgroundColor: '#f8fafc', padding: '20px', borderRadius: '12px', marginBottom: '30px', border: '1px solid #e2e8f0' }}>
            <h3 style={{ marginTop: 0, color: '#2b6cb0' }}>➕ 建立新行程</h3>
            <form onSubmit={handleCreateTrip} style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
              <input type="text" placeholder="輸入行程名稱 (例如: 沖繩五日遊)" value={newTripForm.title} onChange={e => setNewTripForm({ ...newTripForm, title: e.target.value })} required style={{ padding: '12px', borderRadius: '8px', border: '1px solid #cbd5e0', outline: 'none', width: '100%', boxSizing: 'border-box' }} />
              <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                <input type="date" value={newTripForm.start_date} onChange={e => setNewTripForm({ ...newTripForm, start_date: e.target.value })} required style={{ padding: '12px', flex: '1 1 120px', borderRadius: '8px', border: '1px solid #cbd5e0', outline: 'none' }} />
                <input type="date" value={newTripForm.end_date} onChange={e => setNewTripForm({ ...newTripForm, end_date: e.target.value })} required style={{ padding: '12px', flex: '1 1 120px', borderRadius: '8px', border: '1px solid #cbd5e0', outline: 'none' }} />
              </div>
              <button type="submit" style={{ padding: '12px', backgroundColor: '#3182ce', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', fontSize: '1.1em' }}>新增行程</button>
            </form>
          </div>
          <h3 style={{ color: '#4a5568', marginBottom: '15px' }}>📂 選擇現有行程</h3>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {trips.map(trip => (
              <li key={trip.id} onClick={() => selectTrip(trip)} style={{ padding: '20px', backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px', marginBottom: '15px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', transition: 'all 0.2s ease', boxShadow: '0 2px 4px rgba(0,0,0,0.02)', flexWrap: 'wrap', gap: '10px' }} onMouseOver={e => e.currentTarget.style.transform = 'translateY(-2px)'} onMouseOut={e => e.currentTarget.style.transform = 'translateY(0)'}>
                <div>
                  <strong style={{ fontSize: '1.2em', display: 'block', color: '#2d3748', marginBottom: '5px' }}>{trip.title}</strong>
                  <span style={{ fontSize: '0.9em', color: '#718096' }}>📅 {trip.start_date} ~ {trip.end_date}</span>
                </div>
                <span style={{ color: '#3182ce', fontWeight: 'bold', backgroundColor: '#ebf8ff', padding: '8px 12px', borderRadius: '20px' }}>進入管理 ➔</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    )
  }

  // ================= 畫面渲染：行程儀表板 =================
  const renderDayColumn = (day, title = null) => {
    const dayItems = items.filter(item => item.day_number === day).sort((a, b) => a.order_index - b.order_index);
    const isWishlist = day === 0;

    return (
      <div key={`day-container-${day}`} style={{ width: '100%', backgroundColor: isWishlist ? '#ebf8ff' : '#e2e8f0', borderRadius: '16px', padding: '15px', boxSizing: 'border-box', marginBottom: '25px', border: isWishlist ? '2px dashed #90cdf4' : 'none' }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: '15px', padding: '0 5px' }}>
          <span style={{ backgroundColor: '#ffffff', color: isWishlist ? '#2b6cb0' : '#3182ce', padding: '6px 12px', borderRadius: '8px', fontSize: '14px', fontWeight: 'bold', marginRight: '10px', boxShadow: '0 1px 3px rgba(0,0,0,0.1)' }}>
            {title || `Day ${day}`}
          </span>
          {!isWishlist && <span style={{ fontSize: '15px', color: '#4a5568', fontWeight: '600' }}>{getDisplayDate(currentTrip.start_date, day)}</span>}
        </div>

        <Droppable droppableId={`day-${day}`}>
          {(provided, snapshot) => (
            <div {...provided.droppableProps} ref={provided.innerRef} style={{ minHeight: '80px', borderRadius: '12px', transition: 'background-color 0.2s', backgroundColor: snapshot.isDraggingOver ? '#cbd5e0' : 'transparent' }}>
              {dayItems.length === 0 && (
                <div style={{ textAlign: 'center', color: '#a0aec0', padding: '20px 0', border: '2px dashed #cbd5e0', borderRadius: '12px', fontSize: '14px', margin: '5px 0' }}>
                  {isWishlist ? '目前沒有願望清單喔！' : '放鬆的一天，還沒排行程喔！'}
                </div>
              )}

              {dayItems.map((item, index) => (
                <Draggable key={item.id} draggableId={item.id} index={index}>
                  {(provided, snapshot) => (
                    <div ref={provided.innerRef} {...provided.draggableProps} {...provided.dragHandleProps}
                      style={{ userSelect: 'none', padding: '16px', margin: '0 0 10px 0', backgroundColor: '#ffffff', borderRadius: '10px', boxShadow: snapshot.isDragging ? '0 10px 25px rgba(0,0,0,0.15)' : '0 2px 4px rgba(0,0,0,0.05)', ...provided.draggableProps.style }}>

                      {/* === 編輯模式 === */}
                      {editingItemId === item.id ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                          <div style={{ display: 'flex', gap: '10px' }}>
                            <input type="time" value={editItemForm.start_time || ''} onChange={e => setEditItemForm({ ...editItemForm, start_time: e.target.value })} style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e0', outline: 'none' }} />
                            <input type="text" value={editItemForm.content} onChange={e => setEditItemForm({ ...editItemForm, content: e.target.value })} placeholder="景點名稱" style={{ flex: 1, padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e0', outline: 'none' }} />
                          </div>
                          <input type="url" value={editItemForm.map_url || ''} onChange={e => setEditItemForm({ ...editItemForm, map_url: e.target.value })} placeholder="Google Map 連結 (選填)" style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e0', outline: 'none', width: '100%', boxSizing: 'border-box' }} />
                          <textarea value={editItemForm.memo || ''} onChange={e => setEditItemForm({ ...editItemForm, memo: e.target.value })} placeholder="備註事項 (訂位代碼、注意事項...)" rows="2" style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e0', outline: 'none', width: '100%', boxSizing: 'border-box', resize: 'vertical' }} />
                          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                            <button onClick={() => setEditingItemId(null)} style={{ padding: '6px 12px', border: 'none', background: '#e2e8f0', borderRadius: '6px', cursor: 'pointer' }}>取消</button>
                            <button onClick={saveEditedItem} style={{ padding: '6px 12px', border: 'none', background: '#3182ce', color: '#fff', borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold' }}>儲存</button>
                          </div>
                        </div>
                      ) : (
                        /* === 顯示模式 === */
                        <>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                              <span style={{ color: '#a0aec0', fontSize: '18px', cursor: 'grab' }}>⋮⋮</span>
                              {item.start_time && <span style={{ backgroundColor: '#edf2f7', color: '#4a5568', padding: '4px 8px', borderRadius: '6px', fontSize: '0.9em', fontWeight: 'bold' }}>{item.start_time}</span>}
                              <strong style={{ fontSize: '1.1em', color: '#2d3748', wordBreak: 'break-word' }}>{item.content}</strong>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              {item.map_url && <a href={item.map_url} target="_blank" rel="noopener noreferrer" style={{ textDecoration: 'none', fontSize: '1.2em' }} title="開啟 Google Map">📍</a>}
                              <button onClick={() => startEditingItem(item)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.1em' }} title="編輯">✏️</button>
                              <button onClick={() => deleteItem(item.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.1em', color: '#fc8181' }} title="刪除">🗑️</button>
                            </div>
                          </div>
                          {item.memo && (
                            <div style={{ marginTop: '10px', marginLeft: '28px', padding: '10px', backgroundColor: '#fcfaf2', borderLeft: '4px solid #f6e05e', borderRadius: '4px', fontSize: '0.9em', color: '#555', whiteSpace: 'pre-wrap' }}>
                              {item.memo}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </Draggable>
              ))}
              {provided.placeholder}
            </div>
          )}
        </Droppable>
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#f0f4f8', fontFamily: '"Segoe UI", Tahoma, Geneva, Verdana, sans-serif' }}>

      {/* 頂部導覽列 */}
      <div style={{ backgroundColor: '#ffffff', padding: '15px', boxShadow: '0 2px 10px rgba(0,0,0,0.05)', position: 'sticky', top: 0, zIndex: 10 }}>
        <div style={{ maxWidth: '800px', margin: '0 auto', display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
          <button onClick={() => setCurrentTrip(null)} style={{ padding: '8px 16px', cursor: 'pointer', border: '1px solid #e2e8f0', borderRadius: '8px', backgroundColor: '#f8fafc', color: '#4a5568', fontWeight: 'bold' }}>🔙 大廳</button>

          {/* 行程名稱與編輯 */}
          <div style={{ flex: '1 1 200px', textAlign: 'center' }}>
            {isEditingTrip ? (
              <form onSubmit={handleUpdateTrip} style={{ display: 'flex', gap: '5px', justifyContent: 'center' }}>
                <input type="text" value={editTripForm.title} onChange={e => setEditTripForm({ ...editTripForm, title: e.target.value })} style={{ padding: '4px 8px', borderRadius: '4px', border: '1px solid #cbd5e0' }} />
                <button type="submit" style={{ background: '#3182ce', color: '#fff', border: 'none', borderRadius: '4px', padding: '4px 10px', cursor: 'pointer' }}>儲存</button>
              </form>
            ) : (
              <h1 style={{ margin: 0, color: '#1a365d', fontSize: '1.3em', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px' }}>
                {currentTrip.title}
                <button onClick={() => { setIsEditingTrip(true); setEditTripForm(currentTrip); }} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '0.8em', color: '#a0aec0' }}>⚙️</button>
              </h1>
            )}
          </div>

          <div style={{ display: 'flex', gap: '5px' }}>
            <button onClick={() => setActiveTab('itinerary')} style={{ padding: '6px 12px', backgroundColor: activeTab === 'itinerary' ? '#e6fffa' : 'transparent', color: activeTab === 'itinerary' ? '#319795' : '#718096', border: 'none', borderRadius: '20px', cursor: 'pointer', fontWeight: 'bold' }}>📍 看板</button>
            <button onClick={() => setActiveTab('wishlist')} style={{ padding: '6px 12px', backgroundColor: activeTab === 'wishlist' ? '#ebf8ff' : 'transparent', color: activeTab === 'wishlist' ? '#2b6cb0' : '#718096', border: 'none', borderRadius: '20px', cursor: 'pointer', fontWeight: 'bold' }}>✨ 願望</button>
            <button onClick={() => setActiveTab('expenses')} style={{ padding: '6px 12px', backgroundColor: activeTab === 'expenses' ? '#fff5f5' : 'transparent', color: activeTab === 'expenses' ? '#e53e3e' : '#718096', border: 'none', borderRadius: '20px', cursor: 'pointer', fontWeight: 'bold' }}>💰 記帳</button>
          </div>
        </div>
      </div>

      <div style={{ padding: '20px 15px', maxWidth: '800px', margin: '0 auto' }}>

        {/* 新增景點表單 (不適用於記帳本) */}
        {activeTab !== 'expenses' && (
          <form onSubmit={handleAddItem} style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '30px', backgroundColor: '#ffffff', padding: '20px', borderRadius: '12px', boxShadow: '0 4px 6px rgba(0,0,0,0.02)' }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
              {activeTab === 'itinerary' && (
                <select value={selectedDay} onChange={e => setSelectedDay(Number(e.target.value))} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none', fontWeight: 'bold', color: '#2d3748', backgroundColor: '#f8fafc', flex: '1 1 100px' }}>
                  {Array.from({ length: totalDays }, (_, i) => i + 1).map(day => (<option key={day} value={day}>加至 第 {day} 天</option>))}
                </select>
              )}
              <input type="time" value={newItemForm.start_time} onChange={e => setNewItemForm({ ...newItemForm, start_time: e.target.value })} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none' }} title="預計時間" />
              <input type="text" placeholder={activeTab === 'wishlist' ? "加入願望清單..." : "想去的景點..."} value={newItemForm.content} onChange={e => setNewItemForm({ ...newItemForm, content: e.target.value })} required style={{ flex: '3 1 150px', padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none', fontSize: '1em' }} />
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
              <input type="url" placeholder="Google Map 連結 (選填)" value={newItemForm.map_url} onChange={e => setNewItemForm({ ...newItemForm, map_url: e.target.value })} style={{ flex: '2 1 150px', padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none' }} />
              <button type="submit" style={{ padding: '12px 24px', backgroundColor: activeTab === 'wishlist' ? '#3182ce' : '#38b2ac', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', flex: '1 1 100px' }}>＋ 加入</button>
            </div>
            {/* 備註隱藏在選單中，保持 UI 乾淨，編輯時再填寫即可，或在此處開啟 */}
          </form>
        )}

        {/* 顯示願望清單 */}
        {activeTab === 'wishlist' && (
          <DragDropContext onDragEnd={onDragEnd}>
            {renderDayColumn(0, '✨ 我的願望清單 (拖曳排入行程)')}
          </DragDropContext>
        )}

        {/* 顯示行程看板 */}
        {activeTab === 'itinerary' && (
          <DragDropContext onDragEnd={onDragEnd}>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {Array.from({ length: totalDays }, (_, i) => i + 1).map(day => renderDayColumn(day))}
            </div>
          </DragDropContext>
        )}

        {/* 記帳本區塊 */}
        {activeTab === 'expenses' && (
          <div style={{ backgroundColor: '#ffffff', padding: '25px', borderRadius: '16px', boxShadow: '0 10px 30px rgba(0,0,0,0.05)' }}>
            <div style={{ backgroundColor: '#fff5f5', padding: '20px', borderRadius: '12px', marginBottom: '25px', display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
              <h2 style={{ margin: 0, color: '#c53030', fontSize: '1.3em' }}>目前總花費</h2>
              <span style={{ fontSize: '1.8em', fontWeight: 'bold', color: '#e53e3e' }}>{totalExpense.toLocaleString()} <span style={{ fontSize: '0.5em', color: '#f56565' }}>JPY</span></span>
            </div>
            <form onSubmit={handleAddExpense} style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', marginBottom: '30px' }}>
              <input type="number" placeholder="金額 (JPY)" value={newExpense.amount} required onChange={(e) => setNewExpense({ ...newExpense, amount: e.target.value })} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none', flex: '1 1 120px' }} />
              <select value={newExpense.category} onChange={(e) => setNewExpense({ ...newExpense, category: e.target.value })} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none', backgroundColor: '#f8fafc', flex: '1 1 120px' }}>
                <option value="飲食">🍔 飲食</option><option value="交通">🚗 交通</option><option value="門票">🎫 門票</option><option value="購物">🛍️ 購物</option><option value="住宿">🛏️ 住宿</option><option value="其他">❓ 其他</option>
              </select>
              <input type="text" placeholder="消費明細" value={newExpense.description} onChange={(e) => setNewExpense({ ...newExpense, description: e.target.value })} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none', flex: '1 1 100%' }} />
              <select value={newExpense.itemId} onChange={(e) => setNewExpense({ ...newExpense, itemId: e.target.value })} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none', backgroundColor: '#f8fafc', flex: '1 1 100%' }}>
                <option value="">-- 不指定景點 (全旅程共用) --</option>
                {items.filter(i => i.day_number !== 0).sort((a, b) => a.day_number - b.day_number || a.order_index - b.order_index).map(item => (
                  <option key={item.id} value={item.id}>Day {item.day_number} - {item.content}</option>
                ))}
              </select>
              <button type="submit" style={{ padding: '12px', backgroundColor: '#f56565', color: 'white', border: 'none', borderRadius: '8px', fontWeight: 'bold', cursor: 'pointer', flex: '1 1 100%', fontSize: '1.1em' }}>＋ 記一筆</button>
            </form>

            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {expenses.map(exp => {
                const relatedItem = items.find(i => i.id === String(exp.itemId))
                return (
                  <li key={exp.id} style={{ backgroundColor: '#f8fafc', padding: '15px', marginBottom: '10px', borderRadius: '12px', display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', border: '1px solid #e2e8f0', gap: '10px' }}>
                    <div>
                      <strong style={{ color: '#2d3748', fontSize: '1.1em', marginRight: '10px' }}>{exp.category}</strong>
                      <span style={{ color: '#4a5568' }}>{exp.description || '無明細'}</span>
                      {relatedItem && <div style={{ fontSize: '0.85em', color: '#718096', marginTop: '5px' }}>📍 Day {relatedItem.day_number} - {relatedItem.content}</div>}
                    </div>
                    <strong style={{ color: '#e53e3e', fontSize: '1.2em' }}>{exp.amount} <span style={{ fontSize: '0.7em', color: '#a0aec0' }}>JPY</span></strong>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

export default App