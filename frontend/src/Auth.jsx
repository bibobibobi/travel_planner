import React, { useState } from 'react';

export default function Auth({ onLoginSuccess }) {
    const [isLoginMode, setIsLoginMode] = useState(true);
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [errorMessage, setErrorMessage] = useState('');
    const [isLoading, setIsLoading] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setErrorMessage('');
        setIsLoading(true);

        const endpoint = isLoginMode ? '/api/login' : '/api/register';
        const BASE_URL = import.meta.env.VITE_API_URL || '';
        const url = `${BASE_URL}${endpoint}`;

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ email, password }),
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || '發生錯誤，請稍後再試');
            }

            if (isLoginMode) {
                // 🎉 登入成功：存入 Token，並直接切換畫面（已移除 alert 提示）
                localStorage.setItem('travel_token', data.access_token);
                onLoginSuccess();
            } else {
                // 🎉 註冊成功：保留註冊成功的提示讓使用者知道，並切換回登入模式
                alert('註冊成功！請使用新帳號登入。');
                setIsLoginMode(true);
                setPassword('');
            }
        } catch (error) {
            setErrorMessage(error.message);
        } finally {
            setIsLoading(false);
        }
    };

    // 🎨 將樣式集中管理，方便修改與閱讀
    const styles = {
        container: {
            minHeight: '100vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: '#f0f4f8', // 柔和的淺灰藍色背景
            fontFamily: '"Segoe UI", Tahoma, Geneva, Verdana, sans-serif',
            padding: '20px'
        },
        card: {
            backgroundColor: '#ffffff',
            width: '100%',
            maxWidth: '420px',
            padding: '45px 35px',
            borderRadius: '24px', // 圓滑的卡片邊角
            boxShadow: '0 20px 40px rgba(0,0,0,0.08)', // 質感陰影
            boxSizing: 'border-box'
        },
        title: {
            textAlign: 'center',
            color: '#2d3748',
            fontSize: '28px', // 放大標題
            fontWeight: '700',
            marginBottom: '35px',
            marginTop: '0'
        },
        errorBox: {
            backgroundColor: '#fff5f5',
            color: '#c53030',
            padding: '14px',
            borderRadius: '12px',
            marginBottom: '20px',
            fontSize: '15px',
            border: '1px solid #feb2b2',
            textAlign: 'center',
            fontWeight: '600'
        },
        formGroup: {
            marginBottom: '22px'
        },
        label: {
            display: 'block',
            color: '#4a5568',
            fontSize: '16px', // 放大標籤文字
            fontWeight: '600',
            marginBottom: '8px',
            marginLeft: '4px'
        },
        input: {
            width: '100%',
            padding: '15px 18px', // 加大輸入框空間
            fontSize: '16px', // 放大輸入文字
            borderRadius: '16px', // 超柔和圓角輸入框
            border: '2px solid #e2e8f0',
            backgroundColor: '#f8fafc',
            outline: 'none',
            boxSizing: 'border-box',
            color: '#2d3748',
            transition: 'border-color 0.2s, background-color 0.2s'
        },
        button: {
            width: '100%',
            padding: '16px',
            backgroundColor: '#3182ce',
            color: '#ffffff',
            border: 'none',
            borderRadius: '16px', // 圓角按鈕
            fontSize: '18px', // 大按鈕文字
            fontWeight: '700',
            cursor: isLoading ? 'not-allowed' : 'pointer',
            marginTop: '10px',
            boxShadow: '0 4px 15px rgba(49,130,206,0.3)',
            transition: 'transform 0.1s, opacity 0.2s',
            opacity: isLoading ? 0.7 : 1
        },
        footerText: {
            textAlign: 'center',
            marginTop: '25px',
            color: '#718096',
            fontSize: '15px',
            fontWeight: '500'
        },
        toggleBtn: {
            color: '#3182ce',
            fontWeight: '700',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            fontSize: '15px',
            padding: '0 5px',
            outline: 'none',
            textDecoration: 'underline'
        }
    };

    return (
        <div style={styles.container}>
            <div style={styles.card}>
                <h2 style={styles.title}>
                    {isLoginMode ? '✈️ 歡迎回到旅遊記帳' : '📝 建立新帳號'}
                </h2>

                {errorMessage && <div style={styles.errorBox}>{errorMessage}</div>}

                <form onSubmit={handleSubmit}>
                    <div style={styles.formGroup}>
                        <label style={styles.label}>Email 信箱</label>
                        <input
                            type="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            style={styles.input}
                            placeholder="請輸入 Email"
                            required
                        />
                    </div>
                    <div style={styles.formGroup}>
                        <label style={styles.label}>密碼</label>
                        <input
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            style={styles.input}
                            placeholder="請輸入密碼"
                            required
                        />
                    </div>

                    <button type="submit" disabled={isLoading} style={styles.button}>
                        {isLoading ? '處理中...' : (isLoginMode ? '登入' : '註冊')}
                    </button>
                </form>

                <div style={styles.footerText}>
                    {isLoginMode ? '還沒有帳號嗎？' : '已經有帳號了？'}
                    <button
                        type="button"
                        onClick={() => {
                            setIsLoginMode(!isLoginMode);
                            setErrorMessage('');
                        }}
                        style={styles.toggleBtn}
                    >
                        {isLoginMode ? '點我註冊' : '立刻登入'}
                    </button>
                </div>
            </div>
        </div>
    );
}