import { useState, useEffect } from 'react'
import { DragDropContext, Droppable, Draggable } from '@hello-pangea/dnd'
import './App.css'

const API_BASE = '/api'

const ITEM_CATEGORIES = [
  { name: '景點', icon: '📸', color: '#3182ce', bg: '#ebf8ff' },
  { name: '食物', icon: '🍔', color: '#c53030', bg: '#fff5f5' },
  { name: '住宿', icon: '🛏️', color: '#805ad5', bg: '#faf5ff' },
  { name: '逛街', icon: '🛍️', color: '#dd6b20', bg: '#fffff0' },
  { name: '交通', icon: '🚗', color: '#38a169', bg: '#e6fffa' },
  { name: '其他', icon: '❓', color: '#718096', bg: '#f7fafc' }
];

function App() {
  const [trips, setTrips] = useState([])
  const [currentTrip, setCurrentTrip] = useState(null)
  const [editingLobbyTripId, setEditingLobbyTripId] = useState(null)
  const [lobbyEditForm, setLobbyEditForm] = useState({})
  const [newTripForm, setNewTripForm] = useState({ title: '', start_date: '', end_date: '', budget: '' })
  const [activeTab, setActiveTab] = useState('itinerary')
  const [selectedDay, setSelectedDay] = useState(1)
  const [items, setItems] = useState([])
  const [editingItemId, setEditingItemId] = useState(null)
  const [editItemForm, setEditItemForm] = useState({})
  const [newItemForm, setNewItemForm] = useState({ content: '', start_time: '', map_url: '', memo: '', category: '景點' })
  const [shoppingItems, setShoppingItems] = useState([])
  const [newShopForm, setNewShopForm] = useState({ name: '', location: '', item_image: null })
  const [expenses, setExpenses] = useState([])
  const [newExpense, setNewExpense] = useState({ amount: '', category: '飲食', description: '', itemId: '', receipt_image: null })

  // --- 輔助函數 ---
  const getTripDays = (start, end) => {
    const d1 = new Date(start); const d2 = new Date(end);
    return (Math.ceil(Math.abs(d2 - d1) / (1000 * 60 * 60 * 24)) + 1) || 1
  }
  const totalDays = currentTrip ? getTripDays(currentTrip.start_date, currentTrip.end_date) : 1
  const getDisplayDate = (startDate, dayNumber) => {
    if (!startDate || dayNumber === 0) return '';
    const date = new Date(startDate + 'T00:00:00');
    date.setDate(date.getDate() + dayNumber - 1);
    return `${date.getMonth() + 1}/${date.getDate()}`;
  }

  // --- API 呼叫 ---
  useEffect(() => { fetchTrips() }, [])
  const fetchTrips = () => fetch(`${API_BASE}/trips`).then(res => res.json()).then(data => setTrips(Array.isArray(data) ? data : []))
  const selectTrip = (trip) => { setCurrentTrip(trip); setSelectedDay(1); fetchItems(trip.id); fetchExpenses(trip.id); fetchShopping(trip.id); }
  const fetchItems = (tripId) => fetch(`${API_BASE}/items?trip_id=${tripId}`).then(res => res.json()).then(data => setItems(Array.isArray(data) ? data : []))
  const fetchExpenses = (tripId) => fetch(`${API_BASE}/expenses?trip_id=${tripId}`).then(res => res.json()).then(data => setExpenses(Array.isArray(data) ? data : []))
  const fetchShopping = (tripId) => fetch(`${API_BASE}/shopping?trip_id=${tripId}`).then(res => res.json()).then(data => setShoppingItems(Array.isArray(data) ? data : []))

  // --- 動作處理 ---
  const handleCreateTrip = (e) => { e.preventDefault(); fetch(`${API_BASE}/trips`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newTripForm) }).then(() => { fetchTrips(); setNewTripForm({ title: '', start_date: '', end_date: '', budget: '' }) }) }
  const startEditingLobbyTrip = (trip, e) => { e.stopPropagation(); setEditingLobbyTripId(trip.id); setLobbyEditForm(trip) }
  const handleUpdateLobbyTrip = (e) => { e.preventDefault(); fetch(`${API_BASE}/trips/${editingLobbyTripId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(lobbyEditForm) }).then(() => { fetchTrips(); setEditingLobbyTripId(null); }) }
  const handleDeleteTrip = (id, e) => { e.stopPropagation(); if (window.confirm("確定要刪除整個行程嗎？")) { fetch(`${API_BASE}/trips/${id}`, { method: 'DELETE' }).then(() => fetchTrips()) } }

  const handleAddItem = (e) => {
    e.preventDefault(); if (!newItemForm.content) return;
    const orderIndex = items.filter(i => i.day_number === selectedDay).length;
    fetch(`${API_BASE}/items`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ trip_id: currentTrip.id, day_number: selectedDay, order_index: orderIndex, ...newItemForm }) }).then(() => { fetchItems(currentTrip.id); setNewItemForm({ content: '', start_time: '', map_url: '', memo: '', category: '景點' }); })
  }
  const saveEditedItem = () => fetch(`${API_BASE}/items/${editingItemId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(editItemForm) }).then(() => { fetchItems(currentTrip.id); setEditingItemId(null) })
  const deleteItem = (id) => { if (window.confirm("確定要刪除這個景點嗎？")) { fetch(`${API_BASE}/items/${id}`, { method: 'DELETE' }).then(() => fetchItems(currentTrip.id)) } }

  const compressImage = (file) => {
    return new Promise((resolve) => {
      const reader = new FileReader(); reader.readAsDataURL(file);
      reader.onload = (event) => {
        const img = new Image(); img.src = event.target.result;
        img.onload = () => {
          const MAX_WIDTH = 800; const ratio = MAX_WIDTH / img.width;
          const canvas = document.createElement('canvas'); canvas.width = MAX_WIDTH; canvas.height = img.height * ratio;
          const ctx = canvas.getContext('2d'); ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
          canvas.toBlob((blob) => { resolve(new File([blob], file.name, { type: 'image/jpeg' })); }, 'image/jpeg', 0.7);
        };
      };
    });
  };

  const handleAddShop = async (e) => {
    e.preventDefault(); if (!newShopForm.name) return;
    const formData = new FormData();
    formData.append('trip_id', currentTrip.id); formData.append('name', newShopForm.name); formData.append('location', newShopForm.location);
    if (newShopForm.item_image) { const compressed = await compressImage(newShopForm.item_image); formData.append('item_image', compressed); }
    fetch(`${API_BASE}/shopping`, { method: 'POST', body: formData }).then(() => { fetchShopping(currentTrip.id); setNewShopForm({ name: '', location: '', item_image: null }); document.getElementById('shop-upload').value = ''; })
  }
  const toggleBoughtStatus = (item) => { fetch(`${API_BASE}/shopping/${item.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_bought: !item.is_bought }) }).then(() => fetchShopping(currentTrip.id)) }
  const deleteShopItem = (id) => { if (window.confirm("確定刪除這項物品嗎？")) { fetch(`${API_BASE}/shopping/${id}`, { method: 'DELETE' }).then(() => fetchShopping(currentTrip.id)) } }

  const handleAddExpense = async (e) => {
    e.preventDefault(); 
    if (!newExpense.amount) return;
    const formData = new FormData();
    formData.append('trip_id', currentTrip.id); formData.append('amount', newExpense.amount); formData.append('category', newExpense.category); formData.append('description', newExpense.description);
    if (newExpense.itemId) formData.append('itemId', newExpense.itemId);
    if (newExpense.receipt_image) { const compressed = await compressImage(newExpense.receipt_image); formData.append('receipt_image', compressed); }
    fetch(`${API_BASE}/expenses`, { method: 'POST', body: formData }).then(() => { fetchExpenses(currentTrip.id); setNewExpense({ amount: '', category: '飲食', description: '', itemId: '', receipt_image: null }); document.getElementById('receipt-upload').value = ''; })
  }
  const deleteExpense = (id) => { if (window.confirm("確定刪除這筆花費？")) { fetch(`${API_BASE}/expenses/${id}`, { method: 'DELETE' }).then(() => fetchExpenses(currentTrip.id)) } }

  const onDragEnd = (result) => {
    const { source, destination } = result; if (!destination) return;
    const sDay = parseInt(source.droppableId.split('-')[1]); const dDay = parseInt(destination.droppableId.split('-')[1]);
    let newItems = Array.from(items);
    const sItems = newItems.filter(i => i.day_number === sDay).sort((a, b) => a.order_index - b.order_index);
    const [moved] = sItems.splice(source.index, 1); moved.day_number = dDay;
    const dItems = sDay === dDay ? sItems : newItems.filter(i => i.day_number === dDay).sort((a, b) => a.order_index - b.order_index);
    dItems.splice(destination.index, 0, moved);
    const payload = [...sItems.map((it, idx) => ({ id: it.id, order_index: idx, day_number: sDay })), ...dItems.map((it, idx) => ({ id: it.id, order_index: idx, day_number: dDay }))];
    setItems(items.map(it => { const up = payload.find(p => p.id === it.id); return up ? { ...it, ...up } : it; }));
    fetch(`${API_BASE}/items/reorder`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reordered_items: payload }) });
  }

  // 🛡️ 防崩潰總計
  const totalExpense = Array.isArray(expenses) ? expenses.reduce((sum, exp) => sum + (Number(exp.amount) || 0), 0) : 0;

  // --- 樣式設定 ---
  const getTabStyle = (tabName) => ({
    padding: '8px 14px', 
    backgroundColor: activeTab === tabName ? (tabName==='itinerary'?'#e6fffa':tabName==='shopping'?'#ebf8ff':'#fff5f5') : 'transparent', 
    color: activeTab === tabName ? (tabName==='itinerary'?'#319795':tabName==='shopping'?'#2b6cb0':'#e53e3e') : '#718096', 
    border: 'none', borderRadius: '20px', cursor: 'pointer', fontWeight: 600, outline: 'none', fontSize: '0.95em'
  });

  // ================= 渲染：大廳 =================
  if (!currentTrip) {
    return (
      <div style={{ minHeight: '100vh', backgroundColor: '#f0f4f8', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px', fontFamily: '"Segoe UI", sans-serif' }}>
        <div style={{ width: '100%', maxWidth: '600px', backgroundColor: '#ffffff', padding: '30px', borderRadius: '16px', boxShadow: '0 10px 30px rgba(0,0,0,0.05)' }}>
          <h1 style={{ textAlign: 'center', color: '#1a365d', marginBottom: '30px', fontSize: '1.8em', fontWeight: 600 }}>✈️ 我的旅遊管理大廳</h1>
          <div style={{ backgroundColor: '#f8fafc', padding: '20px', borderRadius: '12px', marginBottom: '30px', border: '1px solid #e2e8f0' }}>
            <h3 style={{ marginTop: 0, color: '#2b6cb0', fontWeight: 600 }}>➕ 建立新行程</h3>
            <form onSubmit={handleCreateTrip} style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
              <input type="text" placeholder="行程名稱" value={newTripForm.title} onChange={e => setNewTripForm({ ...newTripForm, title: e.target.value })} required style={{ padding: '12px', borderRadius: '8px', border: '1px solid #cbd5e0', outline: 'none' }} />
              <div style={{ display: 'flex', gap: '10px' }}>
                <input type="date" value={newTripForm.start_date} onChange={e => setNewTripForm({ ...newTripForm, start_date: e.target.value })} required style={{ backgroundColor: '#fff', padding: '12px', flex: 1, borderRadius: '8px', border: '1px solid #cbd5e0', outline: 'none' }} />
                <input type="date" value={newTripForm.end_date} onChange={e => setNewTripForm({ ...newTripForm, end_date: e.target.value })} required style={{ backgroundColor: '#fff', padding: '12px', flex: 1, borderRadius: '8px', border: '1px solid #cbd5e0', outline: 'none' }} />
              </div>
              <button type="submit" style={{ padding: '12px', backgroundColor: '#3182ce', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}>新增行程</button>
            </form>
          </div>
          {trips.map(trip => (
            <div key={trip.id} onClick={() => selectTrip(trip)} style={{ backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px', marginBottom: '15px', padding: '20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', boxShadow: '0 2px 4px rgba(0,0,0,0.02)' }}>
              <div><strong style={{ fontSize: '1.2em', color: '#2d3748' }}>{trip.title}</strong><br /><small style={{ color: '#718096' }}>📅 {trip.start_date} ~ {trip.end_date}</small></div>
              <div style={{ display: 'flex', gap: '10px' }}>
                <button onClick={(e) => startEditingLobbyTrip(trip, e)} style={{ background: 'none', border: 'none', fontSize: '1.2em', cursor: 'pointer', outline: 'none' }}>✏️</button>
                <button onClick={(e) => handleDeleteTrip(trip.id, e)} style={{ background: 'none', border: 'none', fontSize: '1.2em', color: '#fc8181', cursor: 'pointer', outline: 'none' }}>🗑️</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  // ================= 渲染：看板項目 =================
  const renderDayColumn = (day, title = null) => {
    const dayItems = items.filter(item => item.day_number === day).sort((a, b) => a.order_index - b.order_index);
    const isWishlist = day === 0;

    return (
      <div key={`day-container-${day}`} style={{ width: '100%', backgroundColor: isWishlist ? '#ebf8ff' : '#e2e8f0', borderRadius: '16px', padding: '15px', boxSizing: 'border-box', marginBottom: '25px', border: isWishlist ? '2px dashed #90cdf4' : 'none' }}>
        <div style={{ textAlign: 'center', marginBottom: '15px' }}>
          <span style={{ backgroundColor: '#ffffff', color: isWishlist ? '#2b6cb0' : '#4a5568', padding: '6px 16px', borderRadius: '12px', fontSize: '15px', fontWeight: 600, boxShadow: '0 1px 3px rgba(0,0,0,0.1)' }}>
            {title || `Day ${day} (${getDisplayDate(currentTrip.start_date, day)})`}
          </span>
        </div>

        <Droppable droppableId={`day-${day}`}>
          {(provided, snapshot) => (
            <div {...provided.droppableProps} ref={provided.innerRef} style={{ minHeight: '50px', borderRadius: '12px', transition: 'background-color 0.2s', backgroundColor: snapshot.isDraggingOver ? '#cbd5e0' : 'transparent' }}>
              {dayItems.length === 0 && <div style={{ textAlign: 'center', color: '#a0aec0', padding: '20px 0', border: '2px dashed #cbd5e0', borderRadius: '12px', fontSize: '14px', margin: '5px 0' }}>{isWishlist ? '沒有願望？快去新增一些吧！' : '放鬆的一天，還沒排行程喔！'}</div>}
              {dayItems.map((item, index) => {
                const cat = ITEM_CATEGORIES.find(c => c.name === (item.category || '景點')) || ITEM_CATEGORIES[0];
                return (
                  <Draggable key={item.id} draggableId={item.id} index={index}>
                    {(p, s) => (
                      <div ref={p.innerRef} {...p.draggableProps} {...p.dragHandleProps} 
                        style={{ 
                          userSelect: 'none', padding: '16px', margin: '0 0 10px 0', backgroundColor: '#ffffff', borderRadius: '10px', 
                          boxShadow: s.isDragging ? '0 10px 25px rgba(0,0,0,0.15)' : '0 2px 4px rgba(0,0,0,0.05)', 
                          borderLeft: `6px solid ${cat.color}`, ...p.draggableProps.style 
                        }}>
                        {editingItemId === item.id ? (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                              <select value={editItemForm.category || '景點'} onChange={e => setEditItemForm({ ...editItemForm, category: e.target.value })} style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e0', outline: 'none' }}>{ITEM_CATEGORIES.map(c => <option key={c.name} value={c.name}>{c.icon} {c.name}</option>)}</select>
                              <input type="time" value={editItemForm.start_time || ''} onChange={e => setEditItemForm({ ...editItemForm, start_time: e.target.value })} style={{ backgroundColor: '#fff', padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e0', outline: 'none' }} />
                              <input type="text" value={editItemForm.content} onChange={e => setEditItemForm({ ...editItemForm, content: e.target.value })} placeholder="景點名稱" style={{ flex: 1, padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e0', outline: 'none' }} />
                            </div>
                            <input type="url" value={editItemForm.map_url || ''} onChange={e => setEditItemForm({ ...editItemForm, map_url: e.target.value })} placeholder="Google Map 連結" style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e0', width: '100%', boxSizing: 'border-box', outline: 'none' }} />
                            <textarea value={editItemForm.memo || ''} onChange={e => setEditItemForm({ ...editItemForm, memo: e.target.value })} placeholder="備註事項" rows="2" style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e0', width: '100%', boxSizing: 'border-box', resize: 'vertical', outline: 'none' }} />
                            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                              <button onClick={() => setEditingItemId(null)} style={{ padding: '6px 12px', border: 'none', background: '#e2e8f0', borderRadius: '6px', cursor: 'pointer', outline: 'none' }}>取消</button>
                              <button onClick={saveEditedItem} style={{ padding: '6px 12px', border: 'none', background: '#3182ce', color: '#fff', borderRadius: '6px', cursor: 'pointer', fontWeight: 600, outline: 'none' }}>儲存</button>
                            </div>
                          </div>
                        ) : (
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                              <span style={{ fontSize: '1.2em' }}>{cat.icon}</span>
                              {item.start_time && <span style={{ fontSize: '0.85em', fontWeight: 600, background: '#f0f4f8', color: '#4a5568', padding: '2px 6px', borderRadius: '4px' }}>{item.start_time}</span>}
                              <strong style={{ fontSize: '1.1em', color: '#2d3748', wordBreak: 'break-word', fontWeight: 600 }}>{item.content}</strong>
                            </div>
                            <div style={{ display: 'flex', gap: '10px' }}>
                              {item.map_url && <a href={item.map_url} target="_blank" rel="noopener noreferrer" style={{ textDecoration: 'none', fontSize: '1.1em' }}>📍</a>}
                              <button onClick={() => { setEditingItemId(item.id); setEditItemForm(item) }} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.1em', outline: 'none' }}>✏️</button>
                              <button onClick={() => deleteItem(item.id)} style={{ background: 'none', border: 'none', color: '#fc8181', cursor: 'pointer', fontSize: '1.1em', outline: 'none' }}>🗑️</button>
                            </div>
                          </div>
                        )}
                        {!editingItemId && item.memo && <div style={{ marginTop: '10px', marginLeft: '30px', padding: '10px', backgroundColor: '#fcfaf2', borderLeft: '4px solid #f6e05e', borderRadius: '4px', fontSize: '0.9em', color: '#555', whiteSpace: 'pre-wrap' }}>{item.memo}</div>}
                      </div>
                    )}
                  </Draggable>
                )
              })}
              {provided.placeholder}
            </div>
          )}
        </Droppable>
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#f0f4f8', fontFamily: '"Segoe UI", sans-serif' }}>
      <div style={{ backgroundColor: '#ffffff', padding: '15px', boxShadow: '0 2px 10px rgba(0,0,0,0.05)', position: 'sticky', top: 0, zIndex: 10 }}>
        <div style={{ maxWidth: '800px', margin: '0 auto', display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
          <button onClick={() => setCurrentTrip(null)} style={{ padding: '8px 16px', border: '1px solid #e2e8f0', borderRadius: '8px', backgroundColor: '#f8fafc', fontWeight: 600, cursor: 'pointer', outline: 'none', color: '#4a5568' }}>🔙 大廳</button>
          <h1 style={{ margin: 0, color: '#1a365d', fontSize: '1.3em', fontWeight: 600 }}>{currentTrip.title}</h1>
          <div style={{ display: 'flex', gap: '5px' }}>
            <button onClick={() => setActiveTab('itinerary')} style={getTabStyle('itinerary')}>📍 看板</button>
            <button onClick={() => setActiveTab('shopping')} style={getTabStyle('shopping')}>🛒 購物</button>
            <button onClick={() => setActiveTab('expenses')} style={getTabStyle('expenses')}>💰 記帳</button>
          </div>
        </div>
      </div>

      <div style={{ padding: '20px 15px', maxWidth: '800px', margin: '0 auto' }}>
        {/* --- 看板分頁 --- */}
        {activeTab === 'itinerary' && (
          <>
            <form onSubmit={handleAddItem} style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '30px', backgroundColor: '#ffffff', padding: '20px', borderRadius: '12px', boxShadow: '0 4px 6px rgba(0,0,0,0.02)' }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
                <select value={selectedDay} onChange={e => setSelectedDay(Number(e.target.value))} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', fontWeight: 600, color: '#2d3748', backgroundColor: '#f8fafc', flex: '1 1 100px', outline: 'none' }}><option value={0}>✨ 願望清單</option>{Array.from({ length: totalDays }, (_, i) => i + 1).map(day => (<option key={day} value={day}>第 {day} 天</option>))}</select>
                <select value={newItemForm.category} onChange={e => setNewItemForm({ ...newItemForm, category: e.target.value })} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none', backgroundColor: '#fff' }}>{ITEM_CATEGORIES.map(c => <option key={c.name} value={c.name}>{c.icon} {c.name}</option>)}</select>
                <div style={{ display: 'flex', alignItems: 'center', backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '0 10px', flex: '1 1 120px' }}><span>🕒</span><input type="time" value={newItemForm.start_time} onChange={e => setNewItemForm({ ...newItemForm, start_time: e.target.value })} style={{ border: 'none', outline: 'none', padding: '12px 5px', width: '100%', backgroundColor: 'transparent' }} /></div>
                <input type="text" placeholder="想去的景點..." value={newItemForm.content} onChange={e => setNewItemForm({ ...newItemForm, content: e.target.value })} required style={{ flex: '3 1 150px', padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none' }} />
              </div>
              <input type="url" placeholder="Google Map 連結 (選填)" value={newItemForm.map_url} onChange={e => setNewItemForm({ ...newItemForm, map_url: e.target.value })} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none' }} />
              <button type="submit" style={{ padding: '12px', backgroundColor: '#38b2ac', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 600 }}>＋ 加入</button>
            </form>
            <DragDropContext onDragEnd={onDragEnd}><div style={{ display: 'flex', flexDirection: 'column' }}>{renderDayColumn(0, '✨ 願望清單')}{Array.from({ length: totalDays }, (_, i) => i + 1).map(day => renderDayColumn(day))}</div></DragDropContext>
          </>
        )}

        {/* --- 購物分頁 --- */}
        {activeTab === 'shopping' && (
          <div style={{ backgroundColor: '#ffffff', padding: '25px', borderRadius: '16px', boxShadow: '0 10px 30px rgba(0,0,0,0.05)' }}>
            <h2 style={{ color: '#2c7a7b', marginTop: 0, fontWeight: 600 }}>🛒 購物清單</h2>
            <form onSubmit={handleAddShop} style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '25px', background: '#f0f9ff', padding: '20px', borderRadius: '12px', border: '1px solid #bae3ff' }}>
              <input type="text" placeholder="想買什麼？ (如: 防曬乳)" value={newShopForm.name} onChange={e => setNewShopForm({ ...newShopForm, name: e.target.value })} required style={{ padding: '12px', borderRadius: '8px', border: '1px solid #cbd5e0', outline: 'none' }} />
              <input type="text" placeholder="哪裡買？ (如: 機場免稅店)" value={newShopForm.location} onChange={e => setNewShopForm({ ...newShopForm, location: e.target.value })} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #cbd5e0', outline: 'none' }} />
              <div style={{ display: 'flex', gap: '10px' }}>
                <label htmlFor="shop-upload" style={{ flex: 1, padding: '12px', backgroundColor: '#fff', borderRadius: '8px', border: '1px dashed #cbd5e0', textAlign: 'center', cursor: 'pointer', fontWeight: 600, fontSize: '0.9em', color: '#4a5568', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>🖼️ 選擇商品圖片</label>
                <input id="shop-upload" type="file" accept="image/*" onChange={e => setNewShopForm({ ...newShopForm, item_image: e.target.files[0] })} style={{ display: 'none' }} />
                <button type="submit" style={{ flex: 1, padding: '12px', backgroundColor: '#38b2ac', color: 'white', border: 'none', borderRadius: '8px', fontWeight: 600, cursor: 'pointer' }}>＋ 新增</button>
              </div>
            </form>
            <ul style={{ listStyle: 'none', padding: 0 }}>
              {Array.isArray(shoppingItems) && shoppingItems.map(item => (
                <li key={item.id} style={{ display: 'flex', alignItems: 'center', backgroundColor: '#f8fafc', padding: '15px', marginBottom: '10px', borderRadius: '12px', border: '1px solid #e2e8f0', opacity: item.is_bought ? 0.6 : 1 }}>
                  <input type="checkbox" checked={item.is_bought} onChange={() => toggleBoughtStatus(item)} style={{ width: '22px', height: '22px', marginRight: '15px', cursor: 'pointer' }} />
                  {item.image_url && <a href={item.image_url} target="_blank" rel="noopener noreferrer"><img src={item.image_url} alt="商品" style={{ width: '50px', height: '50px', borderRadius: '6px', objectFit: 'cover', marginRight: '15px' }} /></a>}
                  <div style={{ flex: 1, textDecoration: item.is_bought ? 'line-through' : 'none' }}><strong>{item.name}</strong><br /><span style={{ fontSize: '0.85em', color: '#718096' }}>📍 {item.location}</span></div>
                  <button onClick={() => deleteShopItem(item.id)} style={{ background: 'none', border: 'none', color: '#fc8181', cursor: 'pointer', outline: 'none' }}>🗑️</button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* --- 記帳分頁 (含防崩潰) --- */}
        {activeTab === 'expenses' && (
          <div style={{ backgroundColor: '#ffffff', padding: '25px', borderRadius: '16px', boxShadow: '0 10px 30px rgba(0,0,0,0.05)' }}>
            <div style={{ backgroundColor: '#fff5f5', padding: '20px', borderRadius: '12px', marginBottom: '25px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2 style={{ margin: 0, color: '#c53030', fontWeight: 600 }}>目前總花費</h2>
              <span style={{ fontSize: '1.8em', fontWeight: 600, color: '#e53e3e' }}>{totalExpense.toLocaleString()} <span style={{ fontSize: '0.5em', color: '#f56565' }}>JPY</span></span>
            </div>
            <form onSubmit={handleAddExpense} style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '30px', background: '#fffaf0', padding: '20px', borderRadius: '12px', border: '1px solid #f6e05e' }}>
              <div style={{ display: 'flex', gap: '10px' }}><input type="number" placeholder="金額" value={newExpense.amount} required onChange={(e) => setNewExpense({ ...newExpense, amount: e.target.value })} style={{ flex: 1, padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none' }} /><select value={newExpense.category} onChange={(e) => setNewExpense({ ...newExpense, category: e.target.value })} style={{ flex: 1, padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none', backgroundColor: '#fff' }}><option value="飲食">🍔 飲食</option><option value="交通">🚗 交通</option><option value="購物">🛍️ 購物</option><option value="住宿">🛏️ 住宿</option><option value="其他">❓ 其他</option></select></div>
              <input type="text" placeholder="描述" value={newExpense.description} onChange={(e) => setNewExpense({ ...newExpense, description: e.target.value })} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none' }} />
              <div style={{ display: 'flex', gap: '10px' }}><label htmlFor="receipt-upload" style={{ flex: 1, padding: '12px', backgroundColor: '#fff', borderRadius: '8px', border: '1px dashed #cbd5e0', textAlign: 'center', cursor: 'pointer', fontWeight: 600 }}>📸 拍照收據</label><input id="receipt-upload" type="file" accept="image/*" capture="environment" onChange={e => setNewExpense({ ...newExpense, receipt_image: e.target.files[0] })} style={{ display: 'none' }} /><button type="submit" style={{ flex: 1, padding: '12px', backgroundColor: '#f56565', color: 'white', border: 'none', borderRadius: '8px', fontWeight: 600, cursor: 'pointer', outline: 'none' }}>＋ 記一筆</button></div>
            </form>
            <ul style={{ listStyle: 'none', padding: 0 }}>
              {Array.isArray(expenses) && expenses.map(exp => (
                <li key={exp.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '15px', borderBottom: '1px solid #eee' }}>
                  <div><strong style={{ color: '#2d3748' }}>{exp.category}</strong> - <span style={{ color: '#4a5568' }}>{exp.description}</span></div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>{exp.image_url && <a href={exp.image_url} target="_blank" rel="noopener noreferrer">🖼️</a>}<strong>{Number(exp.amount).toLocaleString()} JPY</strong><button onClick={() => deleteExpense(exp.id)} style={{ background: 'none', border: 'none', color: '#fc8181', cursor: 'pointer', outline: 'none' }}>🗑️</button></div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
export default App