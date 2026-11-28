# 候選 GitHub Actions CD

> 正式伺服器安裝順序以 [INSTALL.md](INSTALL.md) 為準；全部驗收前保持 CD 停用。

預設停用：repository variable TRAVEL_CD_ENABLED 未設定或不等於 true 時
build 不執行，production job 不會開始。不要現在設定它。此檔案不安裝
伺服器工具，也不觸發部署。

CI 的同 repository main push 成功完成後，workflow_run 核對 CI 名稱、路徑、
event、branch、conclusion 和來源 repository，並以該次 head SHA checkout
及打包。package_release 從指定 commit 的 git archive 建立乾淨來源，使用
npm ci；既有 Validator 再驗證。Build 不使用 production secrets。
Deploy 僅從同一次 CD run 下載 artifact，核對 build job 傳出的 digest、
revision 與 archive 內的 REVISION；不執行 archive 中的內容。Deploy 只
執行從 workflow 可信 default-branch revision checkout 的必要傳輸程式。

固定 SSH 指令為 deploy-artifact 加 revision 與 sha256；stdin 為原始
Artifact bytes。SSH 的 host/user 格式受到限制，主機金鑰來自 secret，不執行
ssh-keyscan，私鑰及 known_hosts 為 0600 暫存檔。SSH 非零、逾時、
ROLLBACK_OK 或缺少單一 DEPLOY_OK 都是失敗。逾時後應由管理員查看伺服器
transaction 狀態；不要盲目重試，因為遠端可能仍在處理。

Concurrency 不取消進行中的部署，等待者取得執行權後再次透過 GitHub API
確認 revision 仍是 main 最新 SHA。此檢查與遠端切換不是跨系統原子操作：
如果檢查後 main 又前進，舊版可能仍會先完成部署；新版後續 CI 成功才會
再部署。若必須保證切換瞬間永遠等於 main，須額外設計跨系統協調，現有
SSH 協定無法提供此保證。伺服器 lifecycle lock 仍是互斥的最後保護。
[GitHub 文件](https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency)
亦說明等待順序不可當成版本順序保證。

checkout、setup-node、upload-artifact 和 download-artifact 均固定完整 commit。
upload-artifact 的 SHA 對應 [官方 v7.0.2 tag](https://api.github.com/repos/actions/upload-artifact/git/ref/tags/v7.0.2)。
workflow_run 的信任邊界亦須參考
[GitHub 文件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)。

## 正式啟用前

1. 安裝並在 Oracle Ubuntu 22.04、Python 3.10 實際驗收 Receiver、Builder、
   Controller、Pipeline、SSH 固定入口、sudoers 和 Backup V6；驗證
   lifecycle lock 與備份群組、deployment-state、舊版基準清單、備份與還原。
2. 在 GitHub 建立 production environment，限制 main 分支，設定必要審核；
   將四項 TRAVEL_DEPLOY secrets 放在該 environment，使用專用部署帳號、
   專用金鑰和事先驗證的 known_hosts。保護 main、workflow 與審核權限。
3. 依伺服器文件選擇 root-only 的受信任 CI 授權模式；SHA256 是完整性檢查，
   不是身分驗證。部署金鑰外洩時攻擊者可能發布任意 artifact，應撤銷金鑰、
   調查及輪替，並檢查部署紀錄。
4. 在隔離環境跑測試、actionlint，確認 GitHub Environment 審核規則及
   workflow_run 實際 payload 的 gate；確認 action 固定 SHA。完成全部前置
   驗收與審查後，才由管理員將 repository variable
   TRAVEL_CD_ENABLED 設為 true。設定變數不會重播先前已完成的 CI；
   需要之後的 main push 及成功 CI。

## 本機測試

python -m pytest -q tests/test_cd_deploy.py 使用模擬 SSH，沒有 production
secret，也不連線正式主機。actionlint .github/workflows/cd.yml 檢查 GitHub
workflow 語法；需事先在測試環境安裝 actionlint。
# 安裝指引更新

正式伺服器安裝順序以 [INSTALL.md](INSTALL.md) 為準；CD 在全部驗收前保持停用。

