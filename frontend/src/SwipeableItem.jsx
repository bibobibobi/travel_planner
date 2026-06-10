import React, { useState, useRef, useEffect } from 'react';

export default function SwipeableItem({ children, onEdit, onDelete, canEdit, isOpen, onOpen, onClose }) {
    const [translateX, setTranslateX] = useState(0);
    const [isDragging, setIsDragging] = useState(false);
    const startXRef = useRef(0);
    // 新增：記住滑動開始時「當下的 X 座標」
    const currentTranslateXRef = useRef(0);

    const MAX_SWIPE = -100;

    // 💡 優化 1：監聽外部狀態，如果別人打開了，我就乖乖關起來
    useEffect(() => {
        if (!isOpen && !isDragging) {
            setTranslateX(0);
        }
    }, [isOpen, isDragging]);

    const handleStart = (clientX) => {
        if (!canEdit) return;
        startXRef.current = clientX;
        currentTranslateXRef.current = translateX; // 記錄當下位置
        setIsDragging(true);
    };

    const handleMove = (clientX) => {
        if (!canEdit || !isDragging) return;
        const diff = clientX - startXRef.current;

        // 💡 優化 2：以「當下位置」為基準點，加上手指滑動的距離
        let newX = currentTranslateXRef.current + diff;

        // 限制滑動範圍 (往左最多拉一點點彈性，往右不能超過 0)
        if (newX < MAX_SWIPE - 20) newX = MAX_SWIPE - 20;
        if (newX > 0) newX = 0;

        setTranslateX(newX);
    };

    const handleEnd = () => {
        if (!canEdit || !isDragging) return;
        setIsDragging(false);

        // 💡 判斷邏輯升級：根據一開始的狀態，決定是展開還是關閉
        if (currentTranslateXRef.current === 0) {
            // 本來是關的 -> 往左滑超過 30 就打開
            if (translateX < -30) {
                setTranslateX(MAX_SWIPE);
                if (onOpen) onOpen(); // 告訴大廳我打開了
            } else {
                setTranslateX(0);
            }
        } else {
            // 本來是開的 -> 往右滑超過 30 就關閉
            if (translateX > MAX_SWIPE + 30) {
                setTranslateX(0);
                if (onClose) onClose(); // 告訴大廳我關了
            } else {
                setTranslateX(MAX_SWIPE);
            }
        }
    };

    const onTouchStart = (e) => handleStart(e.touches[0].clientX);
    const onTouchMove = (e) => handleMove(e.touches[0].clientX);
    const onTouchEnd = handleEnd;

    const onMouseDown = (e) => handleStart(e.clientX);
    const onMouseMove = (e) => handleMove(e.clientX);
    const onMouseUp = handleEnd;
    const onMouseLeave = handleEnd;

    const styles = {
        container: {
            position: 'relative',
            overflow: 'hidden',
            width: '100%',
            borderRadius: '10px',
            marginBottom: '10px',
            boxShadow: '0 2px 4px rgba(0,0,0,0.05)',
        },
        backgroundLayer: {
            position: 'absolute',
            top: 0,
            right: 0,
            bottom: 0,
            width: '100px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-evenly',
            backgroundColor: '#f8fafc',
            borderLeft: '1px solid #e2e8f0',
            zIndex: 1,
        },
        foregroundLayer: {
            position: 'relative',
            zIndex: 2,
            backgroundColor: '#ffffff',
            transition: isDragging ? 'none' : 'transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275)',
            transform: `translateX(${translateX}px)`,
            width: '100%',
            boxSizing: 'border-box',
        }
    };

    return (
        <div style={styles.container}>
            <div style={styles.backgroundLayer}>
                <button onClick={() => { setTranslateX(0); if (onClose) onClose(); onEdit(); }} style={{ background: '#edf2f7', border: 'none', borderRadius: '6px', padding: '8px', cursor: 'pointer', fontSize: '0.9rem' }}>✏️</button>
                <button onClick={() => { setTranslateX(0); if (onClose) onClose(); onDelete(); }} style={{ background: '#fff5f5', color: '#fc8181', border: 'none', borderRadius: '6px', padding: '8px', cursor: 'pointer', fontSize: '0.9rem' }}>🗑️</button>
            </div>
            <div
                style={styles.foregroundLayer}
                onTouchStart={onTouchStart}
                onTouchMove={onTouchMove}
                onTouchEnd={onTouchEnd}
                onMouseDown={onMouseDown}
                onMouseMove={onMouseMove}
                onMouseUp={onMouseUp}
                onMouseLeave={onMouseLeave}
            >
                {children}
            </div>
        </div>
    );
}