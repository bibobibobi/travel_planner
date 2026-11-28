# Backup V6 候選整合

此目錄是候選版本，不會自行安裝或連線正式主機。原有 backup lock 先取得，
接著以唯讀 fd 8 對既有 `.lifecycle.lock` 取得最多等待 30 秒的排他 flock，
直到驗證、原子發布和保留政策結束才由程序退出釋放。部署持有同一 inode；
備份不建立鎖檔。Release 模式會在持鎖時檢查 root 專用交易狀態，任何
pending（包括 restart_uncertain）皆停止備份，不把當下 current 當健康版本。

Release 的套件清單來自 root 管理的 `venv/BUILD-PACKAGES.txt`。固定 guard
檢查所有祖先、檔案類型、root 擁有權、寫入權限、hardlink 和大小上限；
備份不執行該 Release 的 Python、pip 或應用程式。舊版 baseline 工具只以
系統 Python 讀取已發布 venv 的 `.dist-info/METADATA`，不載入套件程式；
遇到不可信任的路徑、重複套件、egg-info 或無法辨識的 metadata 會拒絕。
套件名稱與版本是資訊清單，並非完整相依來源或產物來源的證明。

## 正式安裝順序（僅供管理員審查後手動執行）

1. 先確認模組 1、2、3B 已依其文件完成安全安裝、已人工初始化並確認目前
   `deployment-state/deployment-state.json` 的 current 與實際健康服務一致，
   沒有 pending transaction。確認 `/usr/local/lib/travel-deploy`、
   `/etc/travel-deploy`、`/opt/travel-app/deployment-state`、
   `/usr/local/sbin/travel-receive-wrapper` 和原有部署工具均已存在，且由 root
   管理；不要將不可信任 Release、staging、incoming、build-work 加入 root tar。
2. 安裝 Ubuntu `acl` 套件，確認 `/usr/bin/getfacl` 存在。使用獨立備份群組
   （例如 `travel-backup`）並將備份執行帳號加入；確認 travel-deploy、
   travel-build、travel-app 不屬於該群組。以 `namei -l`、`getfacl -p` 驗證
   `/opt/travel-app` 及其祖先由 root 擁有且不可由非特權帳號寫入。確認既有
   `/opt/travel-app/.lifecycle.lock` 是 root 擁有的普通檔案、hardlink 數 1，
   沒有額外 ACL，設定 root:travel-backup 0640；不得替換現有 inode。改權限前
   應停止相關排程並確認沒有任何部署或備份持有舊鎖。
3. 將 `travel_backup_guard.py`、`travel_baseline.py` 安裝為 root:root 0644 至
   `/usr/local/lib/travel-deploy/`；將 `travel-backup-guard` 及
   `travel-backup-deployment-archive` 安裝為 root:root 0755 至 `/usr/local/sbin/`。
   這些路徑和祖先必須由 root 管理且不得由其他帳號寫入。確認原始設定及部署
   工具內容中不存在不應納入備份的秘密之外洩風險；備份本身包含敏感資料，
   應限制儲存與還原權限。
4. 如目前健康 Release 缺少清單，以管理員執行
   `sudo /usr/bin/python3 -E -s -B /usr/local/lib/travel-deploy/travel_baseline.py`。
   需先在已持久記錄健康狀態後才可執行；該命令自行取得 lifecycle lock，
   且不覆寫既有清單。對照套件資訊後執行
   `sudo /usr/local/sbin/travel-backup-guard verify-state` 及
   `sudo /usr/local/sbin/travel-backup-guard packages`。已有清單不可盲目重建。
5. 審查 `sudoers.server-backup-additions`，用 `visudo -cf` 檢查候選檔，透過
   `visudo` 安裝為 `/etc/sudoers.d/server-backup-travel` 並檢查整體語法；
   此固定路徑也會納入部署設定備份。這些固定命令不代表限制
   ubuntu 既有完整 sudo 權限，也不是備份帳號遷移。現有 sudoers 的其他備份
   權限仍須保留。鎖群組修改後讓備份程序取得新的群組成員身分。
6. 先以獨立測試環境執行下列 WSL 驗收與正式主機上的唯讀檢查；確認必要
   路徑、鎖 inode、群組、清單與固定 sudo 命令都正常後，暫停備份排程，
   保留原有 `~/scripts/backup.sh` 的 root 保護副本及 checksum，再安裝候選
   腳本；僅在批准的維護時段以備份帳號驗收並重新啟用排程。新腳本保持
   `DRY_RUN=true`、30 天、至少 7 份及 incomplete 7 天原設定。

自動部署啟用後，不可直接恢復會以 ubuntu 執行 Release Python 的舊備份腳本
並繼續 CD；必須先停用 CD、停止並確認無部署／備份交易，改用安全的備份方案，
完成驗證後才可恢復 CD。回復時先停止排程並確認沒有進行中的備份，驗證保留副本的 checksum，將原
`backup.sh` 還原至原路徑並驗證所有權、模式及語法，再恢復排程。不要刪除
或替換仍可能被部署使用的 lifecycle lock；輔助工具和群組可留待確認無使用
後由管理員另行處理。

## WSL 測試

```bash
cd ~/travel-deploy-test/repo
.venv/bin/python -m pytest -q tests
.venv/bin/python -m ruff check deploy/maintenance
for file in deploy/maintenance/backup.sh deploy/maintenance/test-backup-linux.sh \
  deploy/maintenance/test-backup-root.sh deploy/maintenance/travel-backup-guard \
  deploy/maintenance/travel-backup-deployment-archive; do
  bash -n "$file"
done
bash deploy/maintenance/test-backup-cleanup.sh
bash deploy/maintenance/test-backup-linux.sh "$PWD"
```

整合測試需要 sudo、`acl`、useradd/groupadd、runuser 及 bind mount 權限；
會在 `~/travel-deploy-test/backup-test-*` 建獨立資料，在 `/run` 建隨機 bind
mount，建立隨機的 `tbb*`、`tbd*`、`tbu*`、`tba*` 測試帳號及 `tbg*` 群組。
測試只執行隔離的備份函式、普通子程序與虛擬 Release，不修改系統服務或
正式路徑。成功清理測試帳號、群組及掛載後才輸出 `BACKUP_INTEGRATION_OK`；
資料目錄刻意保留，確認輸出路徑後可由使用者自行刪除。若清理失敗，檢查
腳本列出的帳號程序及掛載，再手動解除該次掛載並刪除該次隨機帳號和群組；
不可對其他帳號或路徑執行清理。
