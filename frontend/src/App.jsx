import { useState, useEffect } from 'react'
import { DragDropContext, Droppable, Draggable } from '@hello-pangea/dnd'
import './App.css'

const API_BASE = '/api'

function App() {
  const [trips, setTrips] = useState([])
  const [currentTrip, setCurrentTrip] = useState(null)

  // 大廳編輯用狀態
  const [editingLobbyTripId, setEditingLobbyTripId] = useState(null)
  const [lobbyEditForm, setLobbyEditForm] = useState({})
  const [newTripForm, setNewTripForm] = useState({ title: '', start_date: '', end_date: '', budget: '' })

  const [activeTab, setActiveTab] = useState('itinerary') // 加入 shopping 標籤
  const [selectedDay, setSelectedDay] = useState(1)

  const [items, setItems] = useState([])
  const [editingItemId, setEditingItemId] = useState(null)
  const [editItemForm, setEditItemForm] = useState({})
  const [newItemForm, setNewItemForm] = useState({ content: '', start_time: '', map_url: '', memo: '' })

  // 購物清單用狀態
  const [shoppingItems, setShoppingItems] = useState([])
  const [newShopForm, setNewShopForm] = useState({ name: '', location: '' })
  const [editingShopId, setEditingShopId] = useState(null)
  const [editShopForm, setEditShopForm] = useState({})

  const [expenses, setExpenses] = useState([])
  const [newExpense, setNewExpense] = useState({ amount: '', category: '飲食', description: '', itemId: '' })

  const getTripDays = (start, end) => {
    const d1 = new Date(start)
    const d2 = new Date(end)
    return (Math.ceil(Math.abs(d2 - d1) / (1000 * 60 * 60 * 24)) + 1) || 1
  }
  const totalDays = currentTrip ? getTripDays(currentTrip.start_date, currentTrip.end_date) : 1
  const getDisplayDate = (startDate, dayNumber) => {
    if (!startDate || dayNumber === 0) return '';
    const date = new Date(startDate + 'T00:00:00');
    date.setDate(date.getDate() + dayNumber - 1);
    return `${date.getMonth() + 1}/${date.getDate()}`;
  }

  useEffect(() => { fetchTrips() }, [])
  const fetchTrips = () => fetch(`${API_BASE}/trips`).then(res => res.json()).then(setTrips)

  const selectTrip = (trip) => {
    setCurrentTrip(trip); setSelectedDay(1);
    fetchItems(trip.id); fetchExpenses(trip.id); fetchShopping(trip.id);
  }

  const fetchItems = (tripId) => fetch(`${API_BASE}/items?trip_id=${tripId}`).then(res => res.json()).then(setItems)
  const fetchExpenses = (tripId) => fetch(`${API_BASE}/expenses?trip_id=${tripId}`).then(res => res.json()).then(setExpenses)
  const fetchShopping = (tripId) => fetch(`${API_BASE}/shopping?trip_id=${tripId}`).then(res => res.json()).then(setShoppingItems)

  // --- 大廳行程操作 ---
  const handleCreateTrip = (e) => {
    e.preventDefault()
    fetch(`${API_BASE}/trips`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newTripForm) })
      .then(() => { fetchTrips(); setNewTripForm({ title: '', start_date: '', end_date: '', budget: '' }) })
  }
  const startEditingLobbyTrip = (trip, e) => { e.stopPropagation(); setEditingLobbyTripId(trip.id); setLobbyEditForm(trip) }
  const handleUpdateLobbyTrip = (e) => {
    e.preventDefault()
    fetch(`${API_BASE}/trips/${editingLobbyTripId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(lobbyEditForm) })
      .then(() => { fetchTrips(); setEditingLobbyTripId(null); })
  }
  const handleDeleteTrip = (id, e) => {
    e.stopPropagation()
    if (window.confirm("確定要刪除整個行程嗎？這會刪除所有景點與記帳！")) { fetch(`${API_BASE}/trips/${id}`, { method: 'DELETE' }).then(() => fetchTrips()) }
  }

  // --- 景點操作 ---
  const handleAddItem = (e) => {
    e.preventDefault()
    if (!newItemForm.content) return
    const orderIndex = items.filter(i => i.day_number === selectedDay).length;
    fetch(`${API_BASE}/items`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ trip_id: currentTrip.id, day_number: selectedDay, order_index: orderIndex, ...newItemForm })
    }).then(() => { fetchItems(currentTrip.id); setNewItemForm({ content: '', start_time: '', map_url: '', memo: '' }); })
  }
  const saveEditedItem = () => fetch(`${API_BASE}/items/${editingItemId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(editItemForm) }).then(() => { fetchItems(currentTrip.id); setEditingItemId(null) })
  const deleteItem = (id) => { if (window.confirm("確定要刪除這個景點嗎？")) { fetch(`${API_BASE}/items/${id}`, { method: 'DELETE' }).then(() => fetchItems(currentTrip.id)) } }

  // --- 購物清單操作 ---
  const handleAddShop = (e) => {
    e.preventDefault();
    if (!newShopForm.name) {
      alert("請輸入要購買的物品名稱！");
      return;
    }

    const payload = {
      trip_id: currentTrip.id,
      name: newShopForm.name,
      location: newShopForm.location || ''
    };

    console.log("準備送出的購物資料：", payload); // 幫你在 F12 開發者工具留下線索

    fetch(`${API_BASE}/shopping`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(res => {
        if (!res.ok) {
          throw new Error(`伺服器回應錯誤: ${res.status}`);
        }
        return res.json();
      })
      .then(data => {
        console.log("新增成功，伺服器回傳：", data);
        fetchShopping(currentTrip.id);
        setNewShopForm({ name: '', location: '' });
      })
      .catch(err => {
        console.error("新增購物清單失敗：", err);
        alert("新增失敗，請檢查網路或系統狀態。");
      });
  }
  const toggleBoughtStatus = (item) => {
    fetch(`${API_BASE}/shopping/${item.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_bought: !item.is_bought }) }).then(() => fetchShopping(currentTrip.id))
  }
  const saveEditedShop = () => fetch(`${API_BASE}/shopping/${editingShopId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(editShopForm) }).then(() => { fetchShopping(currentTrip.id); setEditingShopId(null) })
  const deleteShopItem = (id) => { if (window.confirm("確定要刪除這項物品嗎？")) { fetch(`${API_BASE}/shopping/${id}`, { method: 'DELETE' }).then(() => fetchShopping(currentTrip.id)) } }

  // --- 記帳操作 ---
  const handleAddExpense = (e) => {
    e.preventDefault()
    fetch(`${API_BASE}/expenses`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ trip_id: currentTrip.id, itemId: newExpense.itemId, amount: parseFloat(newExpense.amount), category: newExpense.category, description: newExpense.description }) }).then(() => { fetchExpenses(currentTrip.id); setNewExpense({ amount: '', category: '飲食', description: '', itemId: '' }) })
  }
  const deleteExpense = (id) => { if (window.confirm("確定要刪除這筆花費？")) { fetch(`${API_BASE}/expenses/${id}`, { method: 'DELETE' }).then(() => fetchExpenses(currentTrip.id)) } }

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
    const payload = sourceDay === destDay ? sourceItems.map((item, index) => ({ id: item.id, order_index: index, day_number: sourceDay })) : [...sourceItems.map((item, index) => ({ id: item.id, order_index: index, day_number: sourceDay })), ...destItems.map((item, index) => ({ id: item.id, order_index: index, day_number: destDay }))];
    newItems = newItems.map(item => { const up = payload.find(p => p.id === item.id); return up ? { ...item, ...up } : item; });
    setItems(newItems);
    fetch(`${API_BASE}/items/reorder`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reordered_items: payload }) });
  }

  const totalExpense = expenses.reduce((sum, exp) => sum + exp.amount, 0)

  // ================= 渲染：大廳 =================
  if (!currentTrip) {
    return (
      <div style={{ minHeight: '100vh', backgroundColor: '#f0f4f8', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px', fontFamily: '"Segoe UI", Tahoma, Geneva, Verdana, sans-serif' }}>
        <div style={{ width: '100%', maxWidth: '600px', backgroundColor: '#ffffff', padding: '30px', borderRadius: '16px', boxShadow: '0 10px 30px rgba(0,0,0,0.05)' }}>
          <h1 style={{ textAlign: 'center', color: '#1a365d', marginBottom: '30px', fontSize: '1.8em' }}>✈️ 我的旅遊管理大廳</h1>
          <div style={{ backgroundColor: '#f8fafc', padding: '20px', borderRadius: '12px', marginBottom: '30px', border: '1px solid #e2e8f0' }}>
            <h3 style={{ marginTop: 0, color: '#2b6cb0' }}>➕ 建立新行程</h3>
            <form onSubmit={handleCreateTrip} style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
              <input type="text" placeholder="輸入行程名稱 (例如: 沖繩五日遊)" value={newTripForm.title} onChange={e => setNewTripForm({ ...newTripForm, title: e.target.value })} required style={{ padding: '12px', borderRadius: '8px', border: '1px solid #cbd5e0', outline: 'none' }} />
              <div style={{ display: 'flex', gap: '10px' }}>
                <input type="date" value={newTripForm.start_date} onChange={e => setNewTripForm({ ...newTripForm, start_date: e.target.value })} required style={{ padding: '12px', flex: 1, borderRadius: '8px', border: '1px solid #cbd5e0' }} />
                <input type="date" value={newTripForm.end_date} onChange={e => setNewTripForm({ ...newTripForm, end_date: e.target.value })} required style={{ padding: '12px', flex: 1, borderRadius: '8px', border: '1px solid #cbd5e0' }} />
              </div>
              <button type="submit" style={{ padding: '12px', backgroundColor: '#3182ce', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold' }}>新增行程</button>
            </form>
          </div>

          <h3 style={{ color: '#4a5568', marginBottom: '15px' }}>📂 選擇現有行程</h3>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {trips.map(trip => (
              <li key={trip.id} style={{ backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px', marginBottom: '15px', display: 'flex', flexDirection: 'column', boxShadow: '0 2px 4px rgba(0,0,0,0.02)', overflow: 'hidden' }}>
                {editingLobbyTripId === trip.id ? (
                  <form onSubmit={handleUpdateLobbyTrip} style={{ padding: '15px', display: 'flex', flexDirection: 'column', gap: '10px', backgroundColor: '#ebf8ff' }}>
                    <input type="text" value={lobbyEditForm.title} onChange={e => setLobbyEditForm({ ...lobbyEditForm, title: e.target.value })} required style={{ padding: '8px', borderRadius: '4px', border: '1px solid #cbd5e0' }} />
                    <div style={{ display: 'flex', gap: '10px' }}>
                      <input type="date" value={lobbyEditForm.start_date} onChange={e => setLobbyEditForm({ ...lobbyEditForm, start_date: e.target.value })} required style={{ flex: 1, padding: '8px', borderRadius: '4px', border: '1px solid #cbd5e0' }} />
                      <input type="date" value={lobbyEditForm.end_date} onChange={e => setLobbyEditForm({ ...lobbyEditForm, end_date: e.target.value })} required style={{ flex: 1, padding: '8px', borderRadius: '4px', border: '1px solid #cbd5e0' }} />
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                      <button type="button" onClick={() => setEditingLobbyTripId(null)} style={{ padding: '6px 12px', borderRadius: '6px', border: 'none', cursor: 'pointer' }}>取消</button>
                      <button type="submit" style={{ padding: '6px 12px', borderRadius: '6px', border: 'none', backgroundColor: '#3182ce', color: '#fff', cursor: 'pointer' }}>儲存</button>
                    </div>
                  </form>
                ) : (
                  <div onClick={() => selectTrip(trip)} style={{ padding: '20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}>
                    <div>
                      <strong style={{ fontSize: '1.2em', display: 'block', color: '#2d3748', marginBottom: '5px' }}>{trip.title}</strong>
                      <span style={{ fontSize: '0.9em', color: '#718096' }}>📅 {trip.start_date} ~ {trip.end_date}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <button onClick={(e) => startEditingLobbyTrip(trip, e)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.2em' }} title="編輯">✏️</button>
                      <button onClick={(e) => handleDeleteTrip(trip.id, e)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.2em', color: '#fc8181' }} title="刪除">🗑️</button>
                      <span style={{ color: '#3182ce', fontWeight: 'bold', backgroundColor: '#ebf8ff', padding: '8px 12px', borderRadius: '20px', marginLeft: '5px' }}>進入 ➔</span>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    )
  }

  // ================= 渲染：行程儀表板 (Droppable/Draggable) =================
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
                  {isWishlist ? '沒有願望？快去新增一些吧！' : '放鬆的一天，還沒排行程喔！'}
                </div>
              )}
              {dayItems.map((item, index) => (
                <Draggable key={item.id} draggableId={item.id} index={index}>
                  {(provided, snapshot) => (
                    <div ref={provided.innerRef} {...provided.draggableProps} {...provided.dragHandleProps}
                      style={{ userSelect: 'none', padding: '16px', margin: '0 0 10px 0', backgroundColor: '#ffffff', borderRadius: '10px', boxShadow: snapshot.isDragging ? '0 10px 25px rgba(0,0,0,0.15)' : '0 2px 4px rgba(0,0,0,0.05)', ...provided.draggableProps.style }}>

                      {editingItemId === item.id ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                          <div style={{ display: 'flex', gap: '10px' }}>
                            <input type="time" value={editItemForm.start_time || ''} onChange={e => setEditItemForm({ ...editItemForm, start_time: e.target.value })} style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e0' }} />
                            <input type="text" value={editItemForm.content} onChange={e => setEditItemForm({ ...editItemForm, content: e.target.value })} placeholder="景點名稱" style={{ flex: 1, padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e0' }} />
                          </div>
                          <input type="url" value={editItemForm.map_url || ''} onChange={e => setEditItemForm({ ...editItemForm, map_url: e.target.value })} placeholder="Google Map 連結 (選填)" style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e0', width: '100%', boxSizing: 'border-box' }} />
                          <textarea value={editItemForm.memo || ''} onChange={e => setEditItemForm({ ...editItemForm, memo: e.target.value })} placeholder="備註事項 (訂位代碼、注意事項...)" rows="2" style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e0', width: '100%', boxSizing: 'border-box', resize: 'vertical' }} />
                          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                            <button onClick={() => setEditingItemId(null)} style={{ padding: '6px 12px', border: 'none', background: '#e2e8f0', borderRadius: '6px', cursor: 'pointer' }}>取消</button>
                            <button onClick={saveEditedItem} style={{ padding: '6px 12px', border: 'none', background: '#3182ce', color: '#fff', borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold' }}>儲存</button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                              <span style={{ color: '#a0aec0', fontSize: '18px', cursor: 'grab' }}>⋮⋮</span>
                              {item.start_time && <span style={{ backgroundColor: '#edf2f7', color: '#4a5568', padding: '4px 8px', borderRadius: '6px', fontSize: '0.9em', fontWeight: 'bold' }}>{item.start_time}</span>}
                              <strong style={{ fontSize: '1.1em', color: '#2d3748', wordBreak: 'break-word' }}>{item.content}</strong>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              {item.map_url && <a href={item.map_url} target="_blank" rel="noopener noreferrer" style={{ textDecoration: 'none', fontSize: '1.2em' }} title="開啟 Google Map">📍</a>}
                              <button onClick={() => { setEditingItemId(item.id); setEditItemForm(item) }} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.1em' }}>✏️</button>
                              <button onClick={() => deleteItem(item.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.1em', color: '#fc8181' }}>🗑️</button>
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

  // ================= 主結構回傳 =================
  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#f0f4f8', fontFamily: '"Segoe UI", Tahoma, Geneva, Verdana, sans-serif' }}>

      {/* --- 頂部導覽列 --- */}
      <div style={{ backgroundColor: '#ffffff', padding: '15px', boxShadow: '0 2px 10px rgba(0,0,0,0.05)', position: 'sticky', top: 0, zIndex: 10 }}>
        <div style={{ maxWidth: '800px', margin: '0 auto', display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
          <button onClick={() => setCurrentTrip(null)} style={{ padding: '8px 16px', cursor: 'pointer', border: '1px solid #e2e8f0', borderRadius: '8px', backgroundColor: '#f8fafc', color: '#4a5568', fontWeight: 'bold' }}>🔙 大廳</button>
          <h1 style={{ margin: 0, color: '#1a365d', fontSize: '1.3em', textAlign: 'center', flex: '1 1 200px' }}>{currentTrip.title}</h1>
          <div style={{ display: 'flex', gap: '5px' }}>
            <button onClick={() => setActiveTab('itinerary')} style={{ padding: '6px 12px', backgroundColor: activeTab === 'itinerary' ? '#e6fffa' : 'transparent', color: activeTab === 'itinerary' ? '#319795' : '#718096', border: 'none', borderRadius: '20px', cursor: 'pointer', fontWeight: 'bold' }}>📍 看板</button>
            <button onClick={() => setActiveTab('shopping')} style={{ padding: '6px 12px', backgroundColor: activeTab === 'shopping' ? '#ebf8ff' : 'transparent', color: activeTab === 'shopping' ? '#2b6cb0' : '#718096', border: 'none', borderRadius: '20px', cursor: 'pointer', fontWeight: 'bold' }}>🛒 購物</button>
            <button onClick={() => setActiveTab('expenses')} style={{ padding: '6px 12px', backgroundColor: activeTab === 'expenses' ? '#fff5f5' : 'transparent', color: activeTab === 'expenses' ? '#e53e3e' : '#718096', border: 'none', borderRadius: '20px', cursor: 'pointer', fontWeight: 'bold' }}>💰 記帳</button>
          </div>
        </div>
      </div>

      <div style={{ padding: '20px 15px', maxWidth: '800px', margin: '0 auto' }}>

        {/* --- 📍 行程看板分頁 --- */}
        {activeTab === 'itinerary' && (
          <>
            <form onSubmit={handleAddItem} style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '30px', backgroundColor: '#ffffff', padding: '20px', borderRadius: '12px', boxShadow: '0 4px 6px rgba(0,0,0,0.02)' }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
                <select value={selectedDay} onChange={e => setSelectedDay(Number(e.target.value))} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none', fontWeight: 'bold', color: '#2d3748', backgroundColor: '#f8fafc', flex: '1 1 120px' }}>
                  <option value={0}>✨ 願望清單</option>
                  {Array.from({ length: totalDays }, (_, i) => i + 1).map(day => (<option key={day} value={day}>加至 第 {day} 天</option>))}
                </select>
                <input type="time" value={newItemForm.start_time} onChange={e => setNewItemForm({ ...newItemForm, start_time: e.target.value })} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none' }} title="預計時間" />
                <input type="text" placeholder="想去的景點..." value={newItemForm.content} onChange={e => setNewItemForm({ ...newItemForm, content: e.target.value })} required style={{ flex: '3 1 150px', padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none', fontSize: '1em' }} />
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
                <input type="url" placeholder="Google Map 連結 (選填)" value={newItemForm.map_url} onChange={e => setNewItemForm({ ...newItemForm, map_url: e.target.value })} style={{ flex: '2 1 150px', padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none' }} />
                <button type="submit" style={{ padding: '12px 24px', backgroundColor: '#38b2ac', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', flex: '1 1 100px' }}>＋ 加入</button>
              </div>
            </form>

            <DragDropContext onDragEnd={onDragEnd}>
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                {renderDayColumn(0, '✨ 願望清單 (直接拖曳到下方行程)')}
                {Array.from({ length: totalDays }, (_, i) => i + 1).map(day => renderDayColumn(day))}
              </div>
            </DragDropContext>
          </>
        )}

        {/* --- 🛒 購物清單分頁 --- */}
        {activeTab === 'shopping' && (
          <div style={{ backgroundColor: '#ffffff', padding: '25px', borderRadius: '16px', boxShadow: '0 10px 30px rgba(0,0,0,0.05)' }}>
            <h2 style={{ color: '#2c7a7b', marginTop: 0 }}>🛒 購物清單</h2>
            <form onSubmit={handleAddShop} style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginBottom: '25px' }}>
              <input type="text" placeholder="想買什麼？ (如: 防曬乳)" value={newShopForm.name} onChange={e => setNewShopForm({ ...newShopForm, name: e.target.value })} required style={{ flex: '2 1 150px', padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none' }} />
              <input type="text" placeholder="哪裡買？備註 (如: 機場免稅店)" value={newShopForm.location} onChange={e => setNewShopForm({ ...newShopForm, location: e.target.value })} style={{ flex: '2 1 150px', padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none' }} />
              <button type="submit" style={{ padding: '12px 24px', backgroundColor: '#38b2ac', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', flex: '1 1 100px' }}>＋ 新增</button>
            </form>

            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {shoppingItems.map(item => (
                <li key={item.id} style={{ display: 'flex', flexDirection: 'column', backgroundColor: '#f8fafc', padding: '15px', marginBottom: '10px', borderRadius: '12px', border: '1px solid #e2e8f0', transition: 'opacity 0.2s', opacity: item.is_bought ? 0.6 : 1 }}>
                  {editingShopId === item.id ? (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
                      <input type="text" value={editShopForm.name} onChange={e => setEditShopForm({ ...editShopForm, name: e.target.value })} required style={{ flex: 1, padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e0' }} />
                      <input type="text" value={editShopForm.location} onChange={e => setEditShopForm({ ...editShopForm, location: e.target.value })} placeholder="哪裡買？" style={{ flex: 1, padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e0' }} />
                      <button onClick={() => setEditingShopId(null)} style={{ padding: '6px 12px', border: 'none', background: '#e2e8f0', borderRadius: '6px', cursor: 'pointer' }}>取消</button>
                      <button onClick={saveEditedShop} style={{ padding: '6px 12px', border: 'none', background: '#319795', color: '#fff', borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold' }}>儲存</button>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '15px', flex: 1 }}>
                        <input type="checkbox" checked={item.is_bought} onChange={() => toggleBoughtStatus(item)} style={{ width: '22px', height: '22px', cursor: 'pointer', accentColor: '#38b2ac' }} />
                        <div style={{ textDecoration: item.is_bought ? 'line-through' : 'none' }}>
                          <strong style={{ color: '#2d3748', fontSize: '1.1em', display: 'block' }}>{item.name}</strong>
                          {item.location && <span style={{ color: '#718096', fontSize: '0.85em' }}>📍 {item.location}</span>}
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: '10px' }}>
                        <button onClick={() => { setEditingShopId(item.id); setEditShopForm(item); }} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.1em' }} title="編輯">✏️</button>
                        <button onClick={() => deleteShopItem(item.id)} style={{ background: 'none', border: 'none', color: '#fc8181', cursor: 'pointer', fontSize: '1.1em' }} title="刪除">🗑️</button>
                      </div>
                    </div>
                  )}
                </li>
              ))}
              {shoppingItems.length === 0 && <div style={{ textAlign: 'center', color: '#a0aec0', padding: '20px 0' }}>購物清單空空的，沒有想買的東西嗎？</div>}
            </ul>
          </div>
        )}

        {/* --- 💰 旅遊記帳分頁 --- */}
        {activeTab === 'expenses' && (
          <div style={{ backgroundColor: '#ffffff', padding: '25px', borderRadius: '16px', boxShadow: '0 10px 30px rgba(0,0,0,0.05)' }}>
            <div style={{ backgroundColor: '#fff5f5', padding: '20px', borderRadius: '12px', marginBottom: '25px', display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
              <h2 style={{ margin: 0, color: '#c53030', fontSize: '1.3em' }}>目前總花費</h2>
              <span style={{ fontSize: '1.8em', fontWeight: 'bold', color: '#e53e3e' }}>{totalExpense.toLocaleString()} <span style={{ fontSize: '0.5em', color: '#f56565' }}>JPY</span></span>
            </div>
            <form onSubmit={handleAddExpense} style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', marginBottom: '30px' }}>
              <input type="number" placeholder="金額" value={newExpense.amount} required onChange={(e) => setNewExpense({ ...newExpense, amount: e.target.value })} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', flex: '1 1 120px' }} />
              <select value={newExpense.category} onChange={(e) => setNewExpense({ ...newExpense, category: e.target.value })} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', backgroundColor: '#f8fafc', flex: '1 1 120px' }}>
                <option value="飲食">🍔 飲食</option><option value="交通">🚗 交通</option><option value="門票">🎫 門票</option><option value="購物">🛍️ 購物</option><option value="住宿">🛏️ 住宿</option><option value="其他">❓ 其他</option>
              </select>
              <input type="text" placeholder="消費明細" value={newExpense.description} onChange={(e) => setNewExpense({ ...newExpense, description: e.target.value })} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', flex: '1 1 100%' }} />
              <select value={newExpense.itemId} onChange={(e) => setNewExpense({ ...newExpense, itemId: e.target.value })} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', backgroundColor: '#f8fafc', flex: '1 1 100%' }}>
                <option value="">-- 不指定景點 --</option>
                {items.filter(i => i.day_number !== 0).map(item => (<option key={item.id} value={item.id}>Day {item.day_number} - {item.content}</option>))}
              </select>
              <button type="submit" style={{ padding: '12px', backgroundColor: '#f56565', color: 'white', border: 'none', borderRadius: '8px', fontWeight: 'bold', cursor: 'pointer', flex: '1 1 100%' }}>＋ 記一筆</button>
            </form>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {expenses.map(exp => {
                const relatedItem = items.find(i => i.id === String(exp.itemId))
                return (
                  <li key={exp.id} style={{ backgroundColor: '#f8fafc', padding: '15px', marginBottom: '10px', borderRadius: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', border: '1px solid #e2e8f0', gap: '10px' }}>
                    <div>
                      <strong style={{ color: '#2d3748', marginRight: '10px' }}>{exp.category}</strong>
                      <span>{exp.description || '無明細'}</span>
                      {relatedItem && <div style={{ fontSize: '0.85em', color: '#718096', marginTop: '5px' }}>📍 Day {relatedItem.day_number} - {relatedItem.content}</div>}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
                      <strong style={{ color: '#e53e3e', fontSize: '1.2em' }}>{exp.amount} <span style={{ fontSize: '0.7em', color: '#a0aec0' }}>JPY</span></strong>
                      <button onClick={() => deleteExpense(exp.id)} style={{ background: 'none', border: 'none', color: '#fc8181', cursor: 'pointer', fontSize: '1.2em' }} title="刪除記帳">🗑️</button>
                    </div>
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