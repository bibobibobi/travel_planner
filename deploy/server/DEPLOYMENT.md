# 獨立部署控制器（3A 候選）

> 本文件記錄模組開發階段；正式安裝請以 [INSTALL.md](INSTALL.md) 為準。

`deployment_controller.py` 只接受固定操作與 revision，不提供任意服務或路徑參數。
程式與其依賴必須由 root 安裝在 root 擁有、不可由其他帳號寫入的路徑；本提交不
安裝入口。控制器與模組 1／2 使用同一把 lifecycle lock，並在持鎖時保存交易。

初次初始化需要管理員親自核對當前 Release、程式碼來源、systemd／Nginx 設定和
實際服務，再以 root 明確執行 `initialize-existing <revision>`。控制器會確認 current
指向該版本、檢查權限／檔案、服務主程序身分與工作目錄及健康狀態，然後記錄已知健康版本。此顯式管理員
確認是既有無 `.release-ready` 版本的來源信任依據；健康檢查與目錄存在不會證明
程式碼來源。建立狀態後的目標版本仍須有 root 控制且格式正確的 `.release-ready`。

`deploy <revision>` 成功輸出 `DEPLOY_OK`；自動回滾成功輸出 `ROLLBACK_OK`，但
部署仍回傳非零。中斷後以 root 執行 `recover`；無法確認狀態或回滾失敗時保留
pending 記錄並回傳錯誤。`.release-ready` 僅代表建置完成，不代表健康部署。
部署／備份均應依相同 lifecycle lock 協調；Backup V6 的修改不在本階段。

重啟前先持久化 `restart_uncertain`。只有 systemctl 返回，且 systemd 顯示服務
不在轉換狀態、沒有該服務的 job，才清除此標記。客戶端逾時、狀態查詢失敗或
程序在此期間中斷，都會保留 pending 並拒絕一般 `recover` 切換。管理員調查後可
使用僅限 root 的 `recover-uncertain`：先驗證版本並同步停止固定服務，確認無
job 後回復舊版；健康檢查成功才清除 pending。SSH 部署帳號不能呼叫此操作。

模組 3B 串接時必須比對 Receiver 收到的 SHA256、Builder 使用的 SHA256，及目標
Release 的 `.release-ready` 中 SHA256；三者不一致必須拒絕部署。

HTTP 探測在短生命週期的系統 Python 子程序執行，以父程序 timeout 中止慢速連線；
不使用環境代理或 HTTP redirect，並限制回應上限。只檢查固定的 service、localhost
health／ready、正式 HTTPS ready 與首頁 HTML。root 不執行 Release 內任何程式。

## WSL 隔離測試

```bash
cd ~/travel-deploy-test/repo
.venv/bin/python -m pytest -q tests/test_deployment_transaction.py tests/test_deployment_health.py
bash deploy/server/test-deployment-linux.sh "$PWD"
```

整合測試需要 sudo、systemd/cgroup v2 與 bind mount，不下載套件；建立隨機命名的
兩個測試帳號、兩個測試 service，以及家目錄下獨立資料。測試 service 執行的是
root 擁有的 HTTP fixture，而非 Release 內程式。測試以 localhost HTTP 模擬外部
入口，**不驗證正式 HTTPS、憑證、Nginx 或 PostgreSQL**。成功輸出
`DEPLOYMENT_INTEGRATION_OK`。若不能證明測試服務已停止，腳本保留 mount／帳號並
顯示名稱，避免不安全清理；資料目錄本身保留供檢查，成功時印出精確清理指令。

本候選尚待 WSL 實測及 Ubuntu 22.04／Python 3.10 與獨立安全審查，不得安裝至正式環境。
# 安裝指引更新

本文件保留模組開發時的候選狀態；正式安裝請以 [INSTALL.md](INSTALL.md) 為準。

