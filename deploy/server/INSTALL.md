# 正式安裝手冊：候選版本

此手冊供管理員在維護時段審查及手動執行；目前不要連線或安裝。先保留獨立
管理 SSH 工作階段、確認還原方式與近期可還原備份。逐步檢查每個命令的輸出；
遇到不符即停止，不能以改寫正式資料來通過驗收。維持 GitHub repository
variable TRAVEL_CD_ENABLED 未設定或非 true，直到本手冊全部驗收及審查完成。

## 來源清單：不要安裝錯誤版本

以下來源皆為 repository 中相對路徑：

| 正式目標 | 唯一候選來源 | 所有權及 mode |
| --- | --- | --- |
| /usr/local/bin/travel-deploy-entry | deploy/server/travel-deploy-entry.candidate | root:root 0755 |
| /usr/local/sbin/travel-deploy-control | deploy/server/travel-deploy-control.candidate | root:root 0755 |
| /usr/local/sbin/travel-receive-wrapper | deploy/server/receive-wrapper | root:root 0755 |
| /etc/sudoers.d/travel-deploy | deploy/server/sudoers.candidate | root:root 0440 |
| /usr/local/lib/travel-deploy/ | deploy/server/{artifact_stream,receive_artifact,release_builder,release_build_worker,release_tree,deploy_pipeline,deployment_controller,deployment_health,deployment_transaction}.py | root:root 0644，父目錄 0755 |
| /opt/travel-app/tools/validate_artifact.py、extract_artifact.py | scripts/ 對應檔案；優先比對並保留已存在的可信版本 | root:root 0755，父目錄 root 控制 |
| /usr/local/lib/travel-deploy/ | deploy/maintenance/{travel_backup_guard,travel_baseline}.py | root:root 0644 |
| /usr/local/sbin/ | deploy/maintenance/travel-backup-guard、travel-backup-deployment-archive | root:root 0755 |
| /etc/sudoers.d/server-backup-travel | deploy/maintenance/sudoers.server-backup-additions | root:root 0440 |
| ubuntu 的原備份腳本路徑 | deploy/maintenance/backup.sh | 保持原帳號與既有執行權限，父目錄須安全 |

deploy/server 無 candidate 後綴的舊 travel-deploy-entry、travel-deploy-control、
travel_deploy_control.py、build-release 及 sudoers.travel-deploy，不是本次安裝來源。
sudoers.receive-example 和 ssh-receive-fragment.sh 僅供說明；test-*、integration_*
只供隔離測試。既有 RECEIVER.md、RELEASE.md、DEPLOYMENT.md 和 PIPELINE.md
記錄歷史開發階段，其中停用狀態或工具位置可能過時，正式安裝以本表為準。

## 相容性與前置檢查

目標為 Ubuntu 22.04.5、Python 3.10.12、systemd 249、cgroup v2。Python 3.10
語法與 WSL Ubuntu 24.04 的 systemd/cgroup 測試不能證明 systemd 249 實際
執行相容；應先在等版本的隔離環境執行 Receiver、Release、Pipeline、Backup
驗收，尤其測試 transient unit 的所有資源選項、cgroup 停止證明與逾時。
無法證明時不得啟用。RAM 約 956 MiB、available 469 MiB；builder 設定
MemoryMax=350M、MemorySwapMax=512M、CPUQuota=50%、TasksMax=64。這不是
不影響其他服務的保證；先在同等資源環境測試，正式維護時觀察記憶體、swap
與其他服務，資源不足即停止。流程容量檢查不是硬性 filesystem quota。

在管理工作階段先查：

```bash
python3 --version
systemctl --version
stat -fc %T /sys/fs/cgroup
free -h
df -h /opt/travel-app
systemctl is-active travel.service linebot.service link_manager.service
readlink -f /opt/travel-app/current
systemctl show travel.service -p User -p Group -p WorkingDirectory
sudo namei -l /opt/travel-app/current
sudo ls -ld /opt/travel-app/{incoming,staging,tools,build-inputs,prepare,releases,shared}
```

確認 current 是 releases/4ee049b494552afa6cd1856e17e13888ed7b61bc，
服務帳號及 WorkingDirectory 與控制器預期一致，HTTPS 和 localhost 健康及
ready 回傳與 deployment_health.py 的固定內容相符。上述既有目錄、shared/.env、
uploads 及資料庫不可盲目 chown、chmod、覆寫或刪除。特別是現有 shared
root 0750、prepare travel-app 0700、build-inputs root 0750 均先保留。
確認 python3-venv 已安裝；在批准安裝套件後安裝 acl：

```bash
sudo apt-get update
sudo apt-get install acl
command -v getfacl
```

## 備份與帳號

先檢查現有 SSH forced command、authorized_keys、sudoers、systemd、Nginx、
tools、備份腳本和備份 timer，記下原所有權、mode、checksum；將原有檔案以
root-only 權限保存到維護用獨立目錄，並演練回復。保留目前服務及管理 SSH。
不要為測試建立或替換 current、Release 或正式資料。

確認名稱未存在，再建立獨立系統帳號 travel-build（專屬同名 primary group、
無 home、/usr/sbin/nologin）及獨立群組 travel-backup。將執行備份的 ubuntu
加入 travel-backup；重新登入或重啟備份程序以取得群組。不得讓 travel-build
加入 travel-app 或 shared 群組，亦不得讓 travel-deploy、travel-build、
travel-app 加入 travel-backup。以 getent、id -a 和 getfacl 查驗實際群組、
ACL 及祖先穿越權限；不要覆寫 shared 的現有權限。ubuntu 已有完整 sudo，
新增精確規則不會限制它既有的 sudo 權限。

確認名稱及 ID 未被使用後，可執行：

```bash
sudo groupadd --system travel-build
sudo useradd --system --gid travel-build --no-create-home --home-dir /nonexistent \
  --shell /usr/sbin/nologin travel-build
sudo groupadd --system travel-backup
sudo usermod -a -G travel-backup ubuntu
id travel-build
id ubuntu
```

若名稱已存在，先確認其用途與設定，不得擅自變更帳號或群組。

## root 控制目錄與 lifecycle lock

確認 /、/opt、/opt/travel-app 及 /usr/local/lib、/etc 的祖先由 root 擁有且
不可被非特權帳號寫入。以下僅在目錄不存在時建立；若已存在先檢查，勿覆寫：

| 路徑 | 要求 |
| --- | --- |
| /usr/local/lib/travel-deploy | root:root 0755 |
| /etc/travel-deploy | root:root 0700 |
| /opt/travel-app/artifact-snapshots | root:travel-build 0710 |
| /opt/travel-app/build-work | root:root 0711 |
| /opt/travel-app/releases | root 擁有，非特權帳號不可寫入；服務可讀取及穿越 |
| /opt/travel-app/deployment-state | initialize-existing 建立 root:root 0700；狀態檔 root-only |

incoming、staging、build-inputs 應存在，且其既有權限與原 SSH 指令相容；
Receiver 對這些目錄做容量統計，遇特殊檔案會拒絕。快照和 build-work 不可
放入 root tar 備份。檢查 shared 為 root 擁有、other 無權限，travel-build 不在
shared 群組，且實際不能讀取 .env 或 uploads。

在確認沒有部署或備份持鎖時，若 .lifecycle.lock 不存在，僅建立一次普通檔案；
若已存在，確認 root 擁有、非 symlink、link count 為 1，**不得替換 inode**。
使用 root:travel-backup 0640，不能有具名 ACL；父目錄不得由非特權帳號改寫。
使用 stat、getfacl 和 fuser 檢查，確認備份帳號能唯讀開啟並 flock，三個
travel 帳號都無法開啟；必要時只為備份帳號設置祖先穿越權限，勿授寫入。
備份先取得 backup lock 再取得 lifecycle lock；部署只取得後者。

僅在確認目錄不存在後，建立新目錄的範例：

```bash
sudo install -d -o root -g travel-build -m 0710 /opt/travel-app/artifact-snapshots
sudo install -d -o root -g root -m 0711 /opt/travel-app/build-work
```

勿對未審查的既有目錄執行 install -d，它也可能改變既有權限。鎖不存在且
相關程序均已停止時，由 root 以 noclobber 建立一次並設定 root:travel-backup
0640；若已存在，確認 inode 安全且無持鎖程序後才調整權限，不重新建立。

## 工具、設定與初始健康版本

依來源表由 root 安裝檔案，先校驗本地來源及目標的 checksum、LF 和 mode。
工具套件整組複製；不可使用工作目錄或環境變數指定任意 root 程式。保留既有
Validator/Extractor，先確認與 repository 可信版本相同；有差異應審查而非
直接覆蓋。檢查每個 Bash 檔案分別執行 bash -n，sudoers 用 visudo -cf 檢查。

在 /etc/travel-deploy 建立 root-only mode 檔，初始內容為 manual；建立
root-only allowed-artifacts，每行為一個 revision 空格 digest。空 allowlist
允許先測試拒絕，不應用假 digest 進行部署。只有經授權的管理員可變更。
trusted-ci 模式可讓持有專用部署憑證者提交任意 artifact，金鑰外洩會失去
來源授權；不要在初始階段啟用。SHA256 僅保證完整性。

管理員必須先獨立確認現有 current 的來源、程式內容及服務健康，不能只根據
目錄存在或健康檢查判定可信。確認後只執行一次：

```bash
sudo /usr/bin/python3 -E -s -B /usr/local/lib/travel-deploy/deployment_controller.py \
  initialize-existing 4ee049b494552afa6cd1856e17e13888ed7b61bc
```

應輸出 INITIALIZE_OK；此操作檢查 current、權限、服務身分、工作目錄及健康，
並建立 root 控制狀態。若舊 Release 權限、links、REVISION 或 cgroup 不符，
停止並調查，不能以跳過驗證方式初始化。不要重複覆寫既有 deployment-state。
成功後若缺少 BUILD-PACKAGES.txt，依 BACKUP.md 執行 root-only 靜態 baseline，
核對輸出並執行 guard verify-state。清單只是名稱／版本，不證明來源。

## 入口與 Backup V6 安裝

先審查並保存既有 /etc/sudoers.d/travel-deploy 及入口；核對現有規則和
candidate 的固定 status、無參數 receive-wrapper 沒有衝突或額外授權。使用
visudo 安裝候選 sudoers 並檢查整體 sudoers；然後原子替換對應 root-owned
入口與 wrapper，不能改變 authorized_keys 的 forced-command 範圍。
維持管理 SSH，不要透過部署帳號執行 initialize 或 recover。
ping、status、upload-artifact、stage-artifact 仍為既有協定；部署流程只接受
deploy-artifact 的精確 SHA 格式與 stdin。先以既有非破壞性 ping、status
測試，再以隔離資料驗證非法指令及額外參數拒絕。以 sudo -l -U travel-deploy
及 sudo -n -u travel-deploy 執行安全的授權／拒絕測試，檢查不得呼叫任意
shell、路徑、環境、admin recover；不要直接啟動一個空 stdin 的正式部署。
若帳號存在其他 sudo 授權，單靠候選檔無法證明最小權限。

安裝 Backup 的 guard、archive wrapper 及固定 sudoers 檔後，先確認所有 archive
固定目標存在，包括兩個 backup wrapper、server-backup-travel、receive-wrapper、
deployment-state、/etc/travel-deploy 與 /usr/local/lib/travel-deploy。
依 BACKUP.md 停止備份排程、保留原腳本與 checksum，確認鎖及 baseline 後才
替換腳本。以備份帳號驗證鎖競爭、pending 拒絕、完整備份、SHA256SUMS、
原子發布、保留政策與隔離還原；不可執行 Release Python。完成後恢復 timer，
檢查其他專案與服務。備份內含秘密，限制存取。

## 回復與啟用 CD

發現問題先保持或恢復 CD 停用並停備份排程，確認無進行中的部署、備份、job、
builder cgroup 或 pending transaction。pending/restart_uncertain 由 root 依
deployment_controller.py 的 recover 或 recover-uncertain 處理；不得刪除狀態檔、
替換鎖 inode 或自行切換 current。服務恢復須有已知健康版本並重新驗證。
在確認安全後以原 checksum、owner、mode 還原舊入口及 sudoers，驗證 visudo、
SSH 原有四項操作及服務；保留新工具和狀態供調查。自動部署啟用後，禁止直接
恢復會以 ubuntu 執行 Release Python 的舊備份腳本並繼續 CD；須先停用 CD，
以安全備份方案完成驗證後才重新啟用。

最後依 CD.md 建立 production environment、保護分支及 secrets，完成正式主機
和 Python 3.10 驗收、備份還原、SSH/sudo 實測及受信任 CI 授權審查後，才由
管理員決定是否將 TRAVEL_CD_ENABLED 設為 true。這不是本次操作。
