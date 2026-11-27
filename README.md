# Travel Planner｜旅遊行程與記帳管理系統

一個結合旅遊行程規劃與費用管理的全端 Web 應用程式，提供使用者集中安排每日旅遊景點、調整行程順序，以及記錄旅遊支出的功能。

## 專案背景

規劃旅遊時，行程安排與費用紀錄通常分散在不同工具中。當旅遊天數增加，或需要與其他人共同規劃時，容易產生資訊分散、行程修改不便及費用難以統整等問題。

因此，我規劃並開發 Travel Planner，將行程管理與旅遊記帳整合至同一個系統，並採用前後端分離架構，讓功能與系統維護更具彈性。

## 核心功能

- **每日行程管理**：依照旅遊日期分類與管理景點。
- **拖曳式行程排序**：透過 Drag and Drop 調整景點順序。
- **跨日期行程移動**：支援將景點拖曳至不同日期，快速調整旅遊安排。
- **旅遊費用管理**：提供旅遊支出紀錄與管理功能。
- **邀請碼註冊機制**：透過邀請碼控管使用者註冊。
- **API 存取驗證**：在處理資料庫請求前進行環境金鑰驗證，降低未授權存取與自動化惡意註冊的風險。
- **響應式介面**：支援不同尺寸的裝置畫面。

## 系統架構

本專案採用前後端分離架構：

```text
             使用者瀏覽器
                   │
                   ▼
            Nginx Reverse Proxy
                   │
          ┌────────┴────────┐
          │                 │
          ▼                 ▼
     React Frontend     Flask API
          │                 │
          │                 ▼
          │            SQLAlchemy
          │                 │
          │                 ▼
          │             PostgreSQL
          │
          ▼
    使用者操作介面
```

### 部署架構

- **Frontend**：React 建置前端介面，透過 Nginx 提供靜態檔案服務。
- **Backend**：Flask 提供 API，使用 Gunicorn 作為應用程式執行服務。
- **Reverse Proxy**：透過 Nginx 處理前端與後端 API 請求。
- **Database**：使用 PostgreSQL 儲存系統資料。
- **Infrastructure**：部署於 OCI Ubuntu Linux 主機。

### Socket.IO 執行設定

`SOCKETIO_ASYNC_MODE` 預設為 `threading`，供本機開發及 CI 使用；正式環境的 Gevent worker 必須設定為 `gevent`。可用值另包含 `eventlet`，但不得讓 worker 類型與模式不一致。`.env.example` 列出其餘必要環境變數；密鑰與資料庫連線資訊應由各環境安全提供。

正式部署使用 Ubuntu / Python 3.10 虛擬環境，安裝 `pip install -r requirements-prod.txt`。此檔引用基本依賴並另外指定 Gunicorn、gevent、gevent-websocket；開發測試依賴則使用 `requirements-dev.txt`。Eventlet 目前保留。

`travel.service` 未來應在 `[Service]` 中加入 `Environment=SOCKETIO_ASYNC_MODE=gevent`，並使用該虛擬環境中的 Gunicorn，例如：

```ini
Environment=SOCKETIO_ASYNC_MODE=gevent
ExecStart=/path/to/venv/bin/gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 -b 127.0.0.1:5001 app:app
```

請依實際路徑與既有 service 設定調整，並確保 Nginx 代理 `/socket.io/` 的 WebSocket upgrade。Gunicorn 的 Socket.IO 部署應維持單 worker；多程序擴充需要相容的負載平衡、sticky sessions 與共享訊息佇列。本設定不處理 Socket.IO 的 JWT 驗證及 room 授權，正式使用前仍須另行修復。

## 技術架構

| 項目 | 使用技術 |
|---|---|
| 前端 | React、Vite |
| 拖曳互動 | @hello-pangea/dnd |
| 後端 | Python、Flask |
| ORM | SQLAlchemy |
| 資料庫 | PostgreSQL |
| Web Server | Nginx |
| Application Server | Gunicorn |
| 部署環境 | OCI、Ubuntu Linux |

## 開發重點

### 1. 前後端分離架構

將使用者介面與後端 API 分開開發，前端負責行程及費用管理的互動操作，後端負責資料處理與 API 邏輯，讓系統功能具有更清楚的分工。

### 2. 拖曳式行程管理

使用 `@hello-pangea/dnd` 實作拖曳互動，讓使用者能夠直接調整同一天的景點順序，也能將景點移動至其他日期，提升行程編排的操作效率。

### 3. 使用者註冊與 API 存取控管

設計邀請碼註冊機制，並在後端 API 處理資料庫請求前進行環境金鑰驗證，增加系統的存取控管，降低未授權操作與自動化註冊的風險。

### 4. 資料庫架構調整

將原本用於測試的輕量型資料庫遷移至 PostgreSQL，以支援正式部署環境中的資料管理及多使用者使用情境。

### 5. Linux 雲端部署

將系統部署至 OCI Ubuntu 主機，使用 Nginx 提供前端靜態檔案服務及反向代理，並透過 Gunicorn 執行 Flask 後端服務，完成前後端與資料庫的部署整合。

## 專案畫面

### 旅遊行程頁面

<img src="https://github.com/bibobibobi/travel_planner/blob/main/大廳頁面.png" width="400" alt="Demo" />

### 拖曳調整行程

<img src="https://github.com/bibobibobi/travel_planner/blob/main/行程拖曳.gif" width="400" alt="Demo" />

### 旅遊費用管理

<img src="https://github.com/bibobibobi/travel_planner/blob/main/記帳.gif" width="400" alt="Demo" />

## 專案開發方式

本專案由我負責需求規劃、系統功能拆解、前後端整合與部署流程，並運用 AI 協助開發及迭代。

開發過程中，從行程拖曳互動、資料庫架構調整，到 Linux 主機部署與 Nginx 反向代理，逐步完成具備實際使用情境的全端應用程式。
