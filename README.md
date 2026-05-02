# ✈️ Travel Planner - 旅遊行程與記帳管理系統

一個專為旅遊愛好者設計的行程看板與記帳系統，支援 RWD 響應式網頁，手機與電腦皆能完美操作。

## 🛠️ 技術棧 (Tech Stack)
- **前端 (Frontend):** React, `@hello-pangea/dnd` (拖曳套件)
- **後端 (Backend):** Python (Flask), SQLAlchemy, Gunicorn
- **資料庫 (Database):** PostgreSQL
- **伺服器部署 (Deployment):** Oracle Cloud Infrastructure (Ubuntu), Nginx (反向代理)

## 💡 專案亮點
- **生產力看板設計**：支援拖曳功能，可自由排序與跨天數移動景點。
- **全端獨立部署**：於 Linux 雲端主機環境下，獨立設定 Nginx 與 systemd 背景服務。
- **企業級資料庫**：從測試環境的 SQLite 遷移至高效穩定的 PostgreSQL。