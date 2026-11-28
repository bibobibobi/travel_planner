# Release 建置候選工具

> 本文件記錄模組開發階段；正式安裝請以 [INSTALL.md](INSTALL.md) 為準。

`release_builder.py` 接受固定格式的 revision 與 digest，讀取模組 1 的 root 快照；
它不修改 `current`，也不重啟服務。此候選工具尚未安裝或接入 SSH／sudo。

Extractor 與 pip 由獨立非 root 帳號在 transient systemd service 執行。每次以
`KillMode=control-group` 停止並檢查 cgroup 為空，才讀取該階段輸出；無法確認時
保留暫存資料供管理員處理。venv 在預定的最終 Release 路徑建立，停止建置後再
複製成 root 擁有的唯讀樹，並由控制器建立固定的 shared 連結。完成才輸出
`RELEASE_READY`。在最終非 root 驗證和容量檢查後，root 才建立 `.release-ready`
（0444），記錄 `REVISION` 與 `SHA256`。未來的部署控制器必須持 lifecycle lock
檢查此標記、其 root 擁有權與內容；此標記僅代表建置完成，不代表服務健康。
`current` 已存在但損壞時，若指向待建版本，亦拒絕建置。

每個 unit 先等待 root 控制的啟動閘門；控制器觀察到 systemd 回報的實際
`ControlGroup` 後才放行。停止後同時檢查 unit 的載入／執行狀態、待執行 job 和
已觀察到的 cgroup 空置狀態；資訊不足時拒絕發布並保留建置現場。

正式環境需要獨立、無登入 shell 的 `travel-build`，且不在 shared 的群組；
`/opt/travel-app/build-work` 需 root 擁有、0711，`releases` 與快照目錄需為
可信任 root 管理路徑。Extractor 和 Validator 使用既有 `/opt/travel-app/tools`；
Python 工具需安裝於 root 擁有的 `/usr/local/lib/travel-deploy`。安裝及正式使用
仍須經獨立安全審查與實際 Ubuntu 22.04／Python 3.10 驗證。

記憶體 350 MiB、swap 512 MiB、64 tasks、CPU 50%、單檔 200 MiB、暫存 `/tmp`
64 MiB，建置限時 600 秒。`du` 和剩餘空間監控是近似限制，不是硬性 quota；
監控間隔或其他程序寫入仍可能造成瞬間超額。pip 需要可用的套件來源。
容量統計會合併重複或祖先／子目錄路徑，避免將同一棵建置目錄算兩次；發布前後
皆檢查 Release 累積用量和剩餘空間。

## WSL 實際整合測試

```bash
cd ~/travel-deploy-test/repo
bash deploy/server/test-release-linux.sh "$PWD"
```

測試要求 `sudo`、systemd/cgroup v2、`python3-venv`、套件下載網路及可 bind mount。
資料放在 `~/travel-deploy-test/release-integration-*`；測試以 `/run` 下的獨立暫時
bind mount 讓無登入帳號可存取該資料，並建立三個隨機命名的測試帳號與 systemd
單元。結束會停止本次前綴單元、卸載 mount、移除帳號與群組；若清理失敗會印出
精確名稱，保留資料供檢查。只有確認測試單元沒有執行或待執行的工作、cgroup 已
清空且建置帳號沒有程序後，才卸載 mount 及移除帳號。測試成功時輸出
`RELEASE_INTEGRATION_OK`。

測試包含真實 pip 安裝 gunicorn、服務使用者執行 venv、快照與 shared 權限、
重複與容量不足、pip 失敗、cgroup 逾時與背景子程序、特殊檔案拒絕及 current
保持不變。此工具及整合測試尚未經本工作階段的 Linux 執行，請勿直接安裝正式環境。

只重現背景程序及逾時測試（不建立 venv、不下載套件）：

```bash
cd ~/travel-deploy-test/repo
bash deploy/server/test-release-linux.sh "$PWD" --cgroup-only
```

仍需 sudo、systemd/cgroup v2 和 bind mount；成功輸出 `CGROUP_INTEGRATION_OK`。
診斷會列出 systemd-run 的全部選項、unit、閘門、狀態及退出碼；為避免洩漏秘密，
只記錄子程序的執行檔名稱和參數數量，不記錄其參數或環境變數值。
# 安裝指引更新

本文件保留模組開發時的候選狀態；正式安裝請以 [INSTALL.md](INSTALL.md) 為準。

