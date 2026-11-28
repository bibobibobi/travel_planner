# 候選完整部署與 Backup V6 整合

> Backup V6 已納入 deploy/maintenance；下方缺少原始碼的說明屬歷史紀錄。
> 正式安裝請以 [INSTALL.md](INSTALL.md) 與 [BACKUP.md](../maintenance/BACKUP.md) 為準。

`deploy_pipeline.py` 由固定、無參數的 root wrapper 接收標準輸入；以同一個
lifecycle lock 執行 Receiver、Builder 與 Controller。重試會重新接收及驗證
資料，既有快照或 Release 只有在可信且 SHA256 相符時才重用；不完整或摘要
不同的 Release 均拒絕，不刪除。已有待恢復交易時先恢復並要求重新送出請求。
只有 Controller 成功或已部署版本再次通過健康檢查才輸出 `DEPLOY_OK`。

`recover-uncertain` 僅供管理員以 root 執行：持鎖驗證 pending 與 current、
新舊 Release，確認 service 帳號、slice、未委派的 cgroup，執行固定 service 的同步
stop，確認狀態已停止、主程序為零、沒有 job 且 cgroup 無殘留程序後回復舊版，重啟
並通過健康檢查才清除 pending。SSH 候選入口不接受這項命令。停止或狀態無法
確認時不清除不確定標記；若後續重啟逾時，標記再次保留。

## Backup V6 實際檔案尚未納入 repository

你提供的原始碼是伺服器 `~/scripts/backup.sh`，repository 沒有此檔；因此本次
不能直接修改或聲稱已驗證 Backup V6。以下是根據提供內容的最小整合方案，必須
與實際檔案比對及在隔離 Linux 環境驗收後才套用：

1. 保留既有 backup lock，之後、`detect_travel_layout` **之前**以 backup 帳號可讀
   的 root 擁有鎖檔執行 `exec 8</opt/travel-app/.lifecycle.lock` 與 `flock -w 30 8`，
   失敗則停止備份；持有 fd 8 至備份與驗證結束。取得順序固定為 backup lock →
   lifecycle lock；部署只取得 lifecycle lock。正式鎖檔應為 root:獨立備份群組
   0640，且 `travel-deploy` 不得屬於該群組；父目錄 root 擁有且不可由備份帳號
   寫入，備份帳號只能讀取不可替換。隔離測試用 deploy 帳號模擬備份帳號，並非
   正式授權配置。
2. 將 `"$TRAVEL_RELEASE/venv/bin/python" -m pip freeze` 改為讀取 root 保護的
   `"$TRAVEL_RELEASE/venv/BUILD-PACKAGES.txt"`，不得以 ubuntu 或 root 執行
   Release Python。此檔是建置時非 root 產生的名稱／版本清單，並非逐字等同
   `pip freeze`；對缺少清單的舊 Release 必須先由管理員以隔離的非 root 程序
   建立並驗證基準清單，否則安全失敗，不可靜默執行舊命令。清單由非 root 建置
   環境產生、發布後由 root 保護；它不是套件來源的密碼學證明，惡意建置內容可能
   影響其內容。
3. 在現有 root tar 設定備份中，加入 `/opt/travel-app/deployment-state`、
   `/usr/local/lib/travel-deploy`、`/etc/travel-deploy` 與候選控制入口；須配合
   現有精確 sudoers 權限，保留既有 uploads、資料庫、其他專案、manifest 與保留政策。

這些文字不是已套用的正式 Backup V6 修改，尤其不能在持鎖備份執行期間替換鎖檔。
## WSL 測試

```bash
cd ~/travel-deploy-test/repo
.venv/bin/python -m pytest -q tests/test_deploy_pipeline.py tests/test_lifecycle_reuse.py \
  tests/test_deployment_restart.py tests/test_deployment_transaction.py
bash deploy/server/test-pipeline-linux.sh "$PWD"
```

第二個指令先測候選 SSH 相容性，再建立獨立測試帳號、bind mount、隨機 systemd
unit 檔（位於 `/run/systemd/system`），執行真實 Receiver、Validator、Builder、pip 與部署／回滾流程；需要 sudo、
systemd/cgroup v2、`python3-venv` 與下載 Gunicorn 的網路。它不操作現有服務；
成功輸出 `PIPELINE_INTEGRATION_OK`。若無法確認測試程序停止，會保留 mount 與
帳號並印出名稱。清理確認 unit、job、cgroup 與程序停止後，只移除本次建立且 inode
未改變的 unit 檔並執行 `daemon-reload`。測試資料目錄保留供檢查，成功時列出精確清理命令。

只驗證管理員 `recover-uncertain` 的真實 stop／restart，不下載 pip 套件：

```bash
cd ~/travel-deploy-test/repo
bash deploy/server/test-pipeline-linux.sh "$PWD" --recovery-only
```

該模式仍需 sudo、systemd/cgroup v2 與 bind mount；情境與安全清理均成功時輸出
`RECOVERY_INTEGRATION_OK`。它不會執行完整 Receiver／Builder Pipeline。

上述共享鎖、整合及恢復流程尚未在本次修改後執行 WSL 真實測試；正式 Ubuntu
22.04／Python 3.10、Backup V6 補丁與獨立安全審查也仍待完成，不得直接安裝。
# 安裝指引更新

Backup V6 原始碼現已納入 deploy/maintenance；上方「尚未納入」是歷史紀錄。
正式安裝來源、權限與順驟請以 [INSTALL.md](INSTALL.md) 與 [BACKUP.md](../maintenance/BACKUP.md) 為準。

