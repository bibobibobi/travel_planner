import React, { useState } from 'react';

// 這個元件接收一個 onLoginSuccess 函數，登入成功時會呼叫它來通知主程式
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
                // 🎉 登入成功：把 Token 存進隨身包包 (localStorage)
                localStorage.setItem('travel_token', data.access_token);
                onLoginSuccess(); // 通知主程式切換畫面
            } else {
                // 🎉 註冊成功：切換回登入模式讓使用者登入
                alert('註冊成功！請使用新帳號登入。');
                setIsLoginMode(true);
                setPassword(''); // 清空密碼欄位比較安全
            }
        } catch (error) {
            setErrorMessage(error.message);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="min-h-screen bg-gray-100 flex items-center justify-center p-4">
            <div className="max-w-md w-full bg-white rounded-xl shadow-lg p-8">
                <h2 className="text-2xl font-bold text-center text-gray-800 mb-8">
                    {isLoginMode ? '✈️ 歡迎回到旅遊記帳' : '📝 建立新帳號'}
                </h2>

                {errorMessage && (
                    <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
                        {errorMessage}
                    </div>
                )}

                <form onSubmit={handleSubmit} className="space-y-6">
                    <div>
                        <label className="block text-gray-700 text-sm font-bold mb-2">Email</label>
                        <input
                            type="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            className="w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                            required
                        />
                    </div>
                    <div>
                        <label className="block text-gray-700 text-sm font-bold mb-2">密碼</label>
                        <input
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            className="w-full px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                            required
                        />
                    </div>

                    <button
                        type="submit"
                        disabled={isLoading}
                        className="w-full bg-blue-500 hover:bg-blue-600 text-white font-bold py-3 px-4 rounded-lg transition-colors disabled:bg-blue-300"
                    >
                        {isLoading ? '處理中...' : (isLoginMode ? '登入' : '註冊')}
                    </button>
                </form>

                <div className="mt-6 text-center">
                    <button
                        onClick={() => setIsLoginMode(!isLoginMode)}
                        className="text-blue-500 hover:text-blue-700 text-sm font-semibold"
                    >
                        {isLoginMode ? '還沒有帳號？點我註冊' : '已經有帳號了？點我登入'}
                    </button>
                </div>
            </div>
        </div>
    );
}