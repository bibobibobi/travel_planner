# Travel Planner - 旅遊行程與記帳管理系統

一個專為旅遊規劃設計的行程看板與記帳系統。採用前後端分離架構，並具備 RWD 響應式設計，確保在行動裝置與桌面環境皆能提供流暢的使用者體驗。

## 技術棧 (Tech Stack)

- **前端 (Frontend):** React, Vite, `@hello-pangea/dnd` (拖曳排版)
- **後端 (Backend):** Python (Flask), SQLAlchemy, Gunicorn
- **資料庫 (Database):** PostgreSQL
- **部署架構 (Deployment):** Oracle Cloud Infrastructure (Ubuntu), Nginx (反向代理)

## 專案亮點

- **生產力看板設計**
  導入直覺的拖曳互動功能，使用者可自由排序行程並跨天數移動景點，大幅提升規劃效率。
- **邀請碼註冊機制與 API 防護**
  針對公開的雲端伺服器實作環境變數金鑰驗證，在請求進入資料庫前進行攔截，有效阻擋惡意機器人註冊，控管伺服器資源消耗。
- **全端獨立部署與反向代理**
  於 Linux 雲端主機環境建置，配置 Nginx 進行靜態前端網頁託管與後端 API 請求分流，並結合 Gunicorn 將後端封裝為穩定運作的背景服務。
- **企業級關聯式資料庫**
  系統由測試階段的輕量級資料庫遷移並整合至 PostgreSQL，確保多使用者情境下的資料一致性與高穩定性。