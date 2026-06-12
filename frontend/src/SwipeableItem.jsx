import React, { useState, useRef, useEffect } from 'react';

export default function SwipeableItem({ children, onEdit, onDelete, canEdit, isOpen, onOpen, onClose, showEdit = true, deleteIcon = '🗑️' }) {
    const [translateX, setTranslateX] = useState(0);
    const [isDragging, setIsDragging] = useState(false);
    const startXRef = useRef(0);
    const currentTranslateXRef = useRef(0);

    // 新增：用來記錄本次動作究竟是「單純點擊」還是「拖曳滑動」
    const wasDraggedRef = useRef(false);

    const MAX_SWIPE = showEdit ? -100 : -50;

    useEffect(() => {
        if (!isOpen && !isDragging) {
            setTranslateX(0);
        }
    }, [isOpen, isDragging]);

    const handleStart = (clientX) => {
        if (!canEdit) return;
        startXRef.current = clientX;
        currentTranslateXRef.current = translateX;
        setIsDragging(true);
        wasDraggedRef.current = false; // 每次開始動作時，先重置拖曳狀態
    };

    const handleMove = (clientX) => {
        if (!canEdit || !isDragging) return;
        const diff = clientX - startXRef.current;

        // 如果移動距離大於 5 像素，就認定這是一次拖曳滑動，而不是點擊
        if (Math.abs(diff) > 5) {
            wasDraggedRef.current = true;
        }

        let newX = currentTranslateXRef.current + diff;
        if (newX < MAX_SWIPE - 20) newX = MAX_SWIPE - 20;
        if (newX > 0) newX = 0;
        setTranslateX(newX);
    };

    const handleEnd = () => {
        if (!canEdit || !isDragging) return;
        setIsDragging(false);

        if (currentTranslateXRef.current === 0) {
            if (translateX < -30) {
                setTranslateX(MAX_SWIPE);
                if (onOpen) onOpen();
            } else {
                setTranslateX(0);
            }
        } else {
            if (translateX > MAX_SWIPE + 30) {
                setTranslateX(0);
                if (onClose) onClose();
            } else {
                setTranslateX(MAX_SWIPE);
            }
        }
    };

    // 新增：點擊事件防火牆
    const handleClickCapture = (e) => {
        // 情況 1：如果剛才發生過拖曳滑動，攔截點擊事件，不讓它傳到內層的 selectTrip
        if (wasDraggedRef.current) {
            e.stopPropagation();
            e.preventDefault();
            return;
        }

        // 情況 2：如果卡片已經是滑開的狀態，此時點擊主要區域應該是想把它關起來，而不是點進去
        if (translateX !== 0) {
            e.stopPropagation();
            e.preventDefault();
            setTranslateX(0);
            if (onClose) onClose();
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
            width: `${Math.abs(MAX_SWIPE)}px`,
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
            userSelect: 'none',
            width: '100%',
            boxSizing: 'border-box',
        }
    };

    return (
        <div style={styles.container}>
            <div style={styles.backgroundLayer}>
                {showEdit && (
                    <button onClick={() => { setTranslateX(0); if (onClose) onClose(); onEdit(); }} style={{ background: '#edf2f7', border: 'none', borderRadius: '6px', padding: '8px', cursor: 'pointer', fontSize: '0.9rem' }}>✏️</button>
                )}
                <button onClick={() => { setTranslateX(0); if (onClose) onClose(); onDelete(); }} style={{ background: '#fff5f5', color: '#fc8181', border: 'none', borderRadius: '6px', padding: '8px', cursor: 'pointer', fontSize: '0.9rem' }}>{deleteIcon}</button>
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
                onClickCapture={handleClickCapture} // 💡 在這裡綁定防火牆
            >
                {children}
            </div>
        </div>
    );
}