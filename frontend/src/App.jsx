import { useState, useEffect } from 'react'
import { DragDropContext, Droppable, Draggable } from '@hello-pangea/dnd'
import './App.css'

const API_BASE = '/api' 

function App() {
  // ================= 狀態管理 (移除預設標題與日期) =================
  const [trips, setTrips] = useState([])
  const [currentTrip, setCurrentTrip] = useState(null)
  const [newTripForm, setNewTripForm] = useState({
    title: '', start_date: '', end_date: '', budget: ''
  })

  const [activeTab, setActiveTab] = useState('itinerary')
  const [selectedDay, setSelectedDay] = useState(1)

  const [items, setItems] = useState([])
  const [newItemContent, setNewItemContent] = useState('')
  const [expenses, setExpenses] = useState([])
  const [newExpense, setNewExpense] = useState({ amount: '', category: '飲食', description: '', itemId: '' })

  // ================= 輔助函數 =================
  const getTripDays = (start, end) => {
    const d1 = new Date(start)
    const d2 = new Date(end)
    const diffTime = Math.abs(d2 - d1)
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) + 1
    return diffDays > 0 ? diffDays : 1
  }

  const totalDays = currentTrip ? getTripDays(currentTrip.start_date, currentTrip.end_date) : 1

  const getDisplayDate = (startDate, dayNumber) => {
    if (!startDate) return '';
    const date = new Date(startDate + 'T00:00:00');
    date.setDate(date.getDate() + dayNumber - 1);
    return `${date.getMonth() + 1}/${date.getDate()}`;
  }

  // ================= API 呼叫區 =================
  useEffect(() => { fetchTrips() }, [])
  const fetchTrips = () => { fetch(`${API_BASE}/trips`).then(res => res.json()).then(setTrips) }
  const selectTrip = (trip) => { setCurrentTrip(trip); setSelectedDay(1); fetchItems(trip.id); fetchExpenses(trip.id); }
  const fetchItems = (tripId) => { fetch(`${API_BASE}/items?trip_id=${tripId}`).then(res => res.json()).then(setItems) }
  const fetchExpenses = (tripId) => { fetch(`${API_BASE}/expenses?trip_id=${tripId}`).then(res => res.json()).then(setExpenses) }

  const handleCreateTrip = (e) => {
    e.preventDefault()
    fetch(`${API_BASE}/trips`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newTripForm) })
      .then(() => { fetchTrips(); setNewTripForm({ title: '', start_date: '', end_date: '', budget: '' }) })
  }

  const handleAddItem = (e) => {
    e.preventDefault()
    if (!newItemContent) return
    const dayItemsCount = items.filter(i => i.day_number === selectedDay).length;

    fetch(`${API_BASE}/items`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trip_id: currentTrip.id, day_number: selectedDay, content: newItemContent, order_index: dayItemsCount })
    }).then(() => { fetchItems(currentTrip.id); setNewItemContent('') })
  }

  const handleAddExpense = (e) => {
    e.preventDefault()
    if (!newExpense.amount) return
    fetch(`${API_BASE}/expenses`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trip_id: currentTrip.id, itemId: newExpense.itemId, amount: parseFloat(newExpense.amount), category: newExpense.category, description: newExpense.description })
    }).then(() => { fetchExpenses(currentTrip.id); setNewExpense({ amount: '', category: '飲食', description: '', itemId: '' }) })
  }

  const onDragEnd = (result) => {
    const { source, destination } = result;
    if (!destination) return; 

    const sourceDay = parseInt(source.droppableId.split('-')[1]);
    const destDay = parseInt(destination.droppableId.split('-')[1]);
    let newItems = Array.from(items);

    if (sourceDay === destDay) {
      const dayItems = newItems.filter(i => i.day_number === sourceDay).sort((a, b) => a.order_index - b.order_index);
      const [reorderedItem] = dayItems.splice(source.index, 1);
      dayItems.splice(destination.index, 0, reorderedItem);

      const updatedDayItems = dayItems.map((item, index) => ({ ...item, order_index: index }));
      newItems = newItems.map(item => updatedDayItems.find(i => i.id === item.id) || item);
      setItems(newItems);

      const payload = updatedDayItems.map(item => ({ id: item.id, order_index: item.order_index, day_number: sourceDay }));
      fetch(`${API_BASE}/items/reorder`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reordered_items: payload }) });
    } else {
      const sourceItems = newItems.filter(i => i.day_number === sourceDay).sort((a, b) => a.order_index - b.order_index);
      const destItems = newItems.filter(i => i.day_number === destDay).sort((a, b) => a.order_index - b.order_index);

      const [draggedItem] = sourceItems.splice(source.index, 1);
      draggedItem.day_number = destDay;
      destItems.splice(destination.index, 0, draggedItem);

      const updatedSourceItems = sourceItems.map((item, index) => ({ ...item, order_index: index }));
      const updatedDestItems = destItems.map((item, index) => ({ ...item, order_index: index }));

      newItems = newItems.map(item => {
        const sItem = updatedSourceItems.find(i => i.id === item.id);
        if (sItem) return sItem;
        const dItem = updatedDestItems.find(i => i.id === item.id);
        if (dItem) return dItem;
        return item;
      });
      setItems(newItems);

      const payload = [
        ...updatedSourceItems.map(item => ({ id: item.id, order_index: item.order_index, day_number: sourceDay })),
        ...updatedDestItems.map(item => ({ id: item.id, order_index: item.order_index, day_number: destDay }))
      ];
      fetch(`${API_BASE}/items/reorder`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reordered_items: payload }) });
    }
  }

  const totalExpense = expenses.reduce((sum, exp) => sum + exp.amount, 0)

  // ================= 畫面渲染區：大廳 =================
  if (!currentTrip) {
    return (
      <div style={{ minHeight: '100vh', backgroundColor: '#f0f4f8', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px', fontFamily: '"Segoe UI", Tahoma, Geneva, Verdana, sans-serif' }}>
        <div style={{ width: '100%', maxWidth: '600px', backgroundColor: '#ffffff', padding: '30px', borderRadius: '16px', boxShadow: '0 10px 30px rgba(0,0,0,0.05)' }}>
          <h1 style={{ textAlign: 'center', color: '#1a365d', marginBottom: '30px', fontSize: '1.8em' }}>✈️ 我的旅遊管理大廳</h1>
          
          <div style={{ backgroundColor: '#f8fafc', padding: '20px', borderRadius: '12px', marginBottom: '30px', border: '1px solid #e2e8f0' }}>
            <h3 style={{ marginTop: 0, color: '#2b6cb0' }}>➕ 建立新行程</h3>
            <form onSubmit={handleCreateTrip} style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
              <input type="text" placeholder="輸入行程名稱 (例如: 東京五日遊)" value={newTripForm.title} onChange={e => setNewTripForm({ ...newTripForm, title: e.target.value })} required style={{ padding: '12px', borderRadius: '8px', border: '1px solid #cbd5e0', outline: 'none', transition: 'border-color 0.2s', width: '100%', boxSizing: 'border-box' }} />
              <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                <input type="date" value={newTripForm.start_date} onChange={e => setNewTripForm({ ...newTripForm, start_date: e.target.value })} required style={{ padding: '12px', flex: '1 1 120px', borderRadius: '8px', border: '1px solid #cbd5e0', outline: 'none' }} />
                <input type="date" value={newTripForm.end_date} onChange={e => setNewTripForm({ ...newTripForm, end_date: e.target.value })} required style={{ padding: '12px', flex: '1 1 120px', borderRadius: '8px', border: '1px solid #cbd5e0', outline: 'none' }} />
              </div>
              <button type="submit" style={{ padding: '12px', backgroundColor: '#3182ce', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', fontSize: '1.1em', transition: 'background-color 0.2s', boxShadow: '0 4px 6px rgba(49, 130, 206, 0.2)' }}>新增行程</button>
            </form>
          </div>

          <h3 style={{ color: '#4a5568', marginBottom: '15px' }}>📂 選擇現有行程</h3>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {trips.map(trip => (
              <li key={trip.id} onClick={() => selectTrip(trip)} style={{ padding: '20px', backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px', marginBottom: '15px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', transition: 'all 0.2s ease', boxShadow: '0 2px 4px rgba(0,0,0,0.02)', flexWrap: 'wrap', gap: '10px' }} onMouseOver={e => e.currentTarget.style.transform = 'translateY(-2px)'} onMouseOut={e => e.currentTarget.style.transform = 'translateY(0)'}>
                <div>
                  <strong style={{ fontSize: '1.2em', display: 'block', color: '#2d3748', marginBottom: '5px' }}>{trip.title}</strong>
                  <span style={{ fontSize: '0.9em', color: '#718096', display: 'flex', alignItems: 'center', gap: '5px' }}>📅 {trip.start_date} ~ {trip.end_date}</span>
                </div>
                <span style={{ color: '#3182ce', fontWeight: 'bold', backgroundColor: '#ebf8ff', padding: '8px 12px', borderRadius: '20px', whiteSpace: 'nowrap' }}>進入管理 ➔</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    )
  }

  // ================= 畫面渲染區：行程儀表板 (垂直排列響應式版) =================
  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#f0f4f8', fontFamily: '"Segoe UI", Tahoma, Geneva, Verdana, sans-serif' }}>
      
      {/* 頂部導覽列：響應式自動換行 */}
      <div style={{ backgroundColor: '#ffffff', padding: '15px', boxShadow: '0 2px 10px rgba(0,0,0,0.05)', position: 'sticky', top: 0, zIndex: 10 }}>
        <div style={{ maxWidth: '800px', margin: '0 auto', display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
          <button onClick={() => setCurrentTrip(null)} style={{ padding: '8px 16px', cursor: 'pointer', border: '1px solid #e2e8f0', borderRadius: '8px', backgroundColor: '#f8fafc', color: '#4a5568', fontWeight: 'bold', flexShrink: 0 }}>🔙 回大廳</button>
          <h1 style={{ margin: 0, color: '#1a365d', fontSize: '1.3em', textAlign: 'center', flex: '1 1 200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{currentTrip.title}</h1>
          
          <div style={{ display: 'flex', gap: '10px', flexShrink: 0 }}>
            <button onClick={() => setActiveTab('itinerary')} style={{ padding: '8px 16px', backgroundColor: activeTab === 'itinerary' ? '#e6fffa' : 'transparent', color: activeTab === 'itinerary' ? '#319795' : '#718096', border: 'none', borderRadius: '20px', cursor: 'pointer', fontWeight: 'bold' }}>📍 行程看板</button>
            <button onClick={() => setActiveTab('expenses')} style={{ padding: '8px 16px', backgroundColor: activeTab === 'expenses' ? '#fff5f5' : 'transparent', color: activeTab === 'expenses' ? '#e53e3e' : '#718096', border: 'none', borderRadius: '20px', cursor: 'pointer', fontWeight: 'bold' }}>💰 記帳本</button>
          </div>
        </div>
      </div>

      <div style={{ padding: '20px 15px', maxWidth: '800px', margin: '0 auto' }}>
        {/* ================= 垂直看板模式 UI ================= */}
        {activeTab === 'itinerary' && (
          <>
            <form onSubmit={handleAddItem} style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginBottom: '30px', backgroundColor: '#ffffff', padding: '20px', borderRadius: '12px', boxShadow: '0 4px 6px rgba(0,0,0,0.02)' }}>
              <select value={selectedDay} onChange={e => setSelectedDay(Number(e.target.value))} style={{ padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none', fontWeight: 'bold', color: '#2d3748', backgroundColor: '#f8fafc', flex: '1 1 100px' }}>
                {Array.from({ length: totalDays }, (_, i) => i + 1).map(day => (
                  <option key={day} value={day}>加至 第 {day} 天</option>
                ))}
              </select>
              <input type="text" placeholder="想去的景點..." value={newItemContent} onChange={e => setNewItemContent(e.target.value)} required style={{ flex: '3 1 200px', padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', outline: 'none', fontSize: '1em' }} />
              <button type="submit" style={{ padding: '12px 24px', backgroundColor: '#38b2ac', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: 'bold', boxShadow: '0 4px 6px rgba(56, 178, 172, 0.2)', flex: '1 1 100px' }}>＋ 加入</button>
            </form>

            {/* 垂直排列的 Kanban 區域 */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '25px', paddingBottom: '30px' }}>
              <DragDropContext onDragEnd={onDragEnd}>
                {Array.from({ length: totalDays }, (_, i) => i + 1).map(day => {
                  const dayItems = items.filter(item => item.day_number === day).sort((a, b) => a.order_index - b.order_index);

                  return (
                    <div key={`day-container-${day}`} style={{ width: '100%', backgroundColor: '#e2e8f0', borderRadius: '16px', padding: '15px', boxSizing: 'border-box' }}>
                      
                      <div style={{ display: 'flex', alignItems: 'center', marginBottom: '15px', padding: '0 5px' }}>
                        <span style={{ backgroundColor: '#ffffff', color: '#3182ce', padding: '6px 12px', borderRadius: '8px', fontSize: '14px', fontWeight: 'bold', marginRight: '10px', boxShadow: '0 1px 3px rgba(0,0,0,0.1)' }}>Day {day}</span>
                        <span style={{ fontSize: '15px', color: '#4a5568', fontWeight: '600' }}>{getDisplayDate(currentTrip.start_date, day)}</span>
                      </div>

                      <Droppable droppableId={`day-${day}`}>
                        {(provided, snapshot) => (
                          <div
                            {...provided.droppableProps} ref={provided.innerRef}
                            style={{ minHeight: '80px', borderRadius: '12px', transition: 'background-color 0.2s', backgroundColor: snapshot.isDraggingOver ? '#cbd5e0' : 'transparent' }}
                          >
                            {dayItems.length === 0 && (
                              <div style={{ textAlign: 'center', color: '#a0aec0', padding: '20px 0', border: '2px dashed #cbd5e0', borderRadius: '12px', fontSize: '14px', margin: '5px 0' }}>
                                放鬆的一天，還沒排行程喔！
                              </div>
                            )}

                            {dayItems.map((item, index) => (
                              <Draggable key={item.id} draggableId={item.id} index={index}>
                                {(provided, snapshot) => (
                                  <div ref={provided.innerRef} {...provided.draggableProps} {...provided.dragHandleProps} 
                                       style={{ userSelect: 'none', padding: '16px', margin: '0 0 10px 0', backgroundColor: '#ffffff', color: '#2d3748', borderRadius: '10px', boxShadow: snapshot.isDragging ? '0 10px 25px rgba(0,0,0,0.15)' : '0 2px 4px rgba(0,0,0,0.05)', display: 'flex', alignItems: 'center', ...provided.draggableProps.style }}>
                                    <span style={{ marginRight: '12px', color: '#a0aec0', fontSize: '18px' }}>⋮⋮</span>
                                    <strong style={{ fontSize: '15px', lineHeight: '1.4', wordBreak: 'break-word' }}>{item.content}</strong>
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
                })}
              </DragDropContext>
            </div>
          </>
        )}

        {/* ================= 記帳本區塊 (響應式更新) ================= */}
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
                {items.sort((a, b) => a.day_number - b.day_number || a.order_index - b.order_index).map(item => (
                  <option key={item.id} value={item.id}>Day {item.day_number} - {item.content}</option>
                ))}
              </select>
              <button type="submit" style={{ padding: '12px', backgroundColor: '#f56565', color: 'white', border: 'none', borderRadius: '8px', fontWeight: 'bold', cursor: 'pointer', flex: '1 1 100%', fontSize: '1.1em', boxShadow: '0 4px 6px rgba(245, 101, 101, 0.2)' }}>＋ 記一筆</button>
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