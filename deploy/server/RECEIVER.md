# Artifact 接收模組（尚未開啟）

> 本文件記錄模組開發階段；正式安裝請以 [INSTALL.md](INSTALL.md) 為準。

現有候選部署入口保持停用。`ssh-receive-fragment.sh` 只展示在現有正式 Bash
入口的 ping/status case 與原本 regex 之間加入的分支，既有四個指令不應修改。
`receive-wrapper` 不接受參數，sudoers 僅允許此固定命令；Python 再獨立檢查
固定格式 header。二進位 stdin 直接進入 root 建立的快照，不讀取部署帳號提供的路徑。

人工模式 `/etc/travel-deploy/mode` 內容為 `manual`，`allowed-artifacts` 每行
為 `<40位revision> <64位digest>`。`trusted-ci` 模式不核對 allowlist，任何能使用
此專用 SSH 憑證者均可提出任意 artifact；金鑰外洩即喪失來源授權。設定與所有
父目錄須 root 擁有且不得由 group/other 寫入。兩種模式均驗證 SHA256 和 artifact。

`artifact-snapshots` 應為 root:travel-build 0710，快照為 root:travel-build 0440；
travel-deploy 不得是 travel-build 的成員。Validator 與其祖先須 root 擁有、不可
由 group/other 寫入，沿用 `/opt/travel-app/tools/validate_artifact.py`。部署帳號
不可存取快照目錄。為 Backup V6 建立 root 擁有、backup 群組可開啟的 lifecycle
lock，backup 先取得自己的 backup lock，再取得 lifecycle lock；新接收流程只取得
lifecycle lock，不取得 upload lock，現有 upload 流程只取得 upload lock，因此不
形成反向取得順序。此接收流程本身不切換 current。

容量檢查是流程內保守限額，不是 filesystem quota；其他程序仍可能同時寫入。
容量檢查對特殊檔案失敗關閉。尚未驗證 Linux 實際帳號、鎖、Validator 和 sudo；
不得在正式環境安裝。未提供正式安裝命令以避免誤啟用。

## WSL 測試

以一般使用者執行下列指令；腳本會要求 sudo 執行測試，僅在該使用者的
`~/travel-deploy-test/receiver-test-*` 新目錄建立檔案。它使用現有執行者帳號作為
非 root validator，並使用 nobody 模擬部署帳號，不建立帳號或 systemd unit：

```bash
cd ~/travel-deploy-test/repo
bash deploy/server/test-receiver-linux.sh "$PWD"
```

測試涵蓋真實快照、現有 Validator、授權拒絕、容量拒絕、重複快照、失敗清理、
validator 帳號無寫入權、FIFO／symlink／hardlink 和跨程序 flock 競爭。因為使用者
家目錄本來由使用者擁有，測試只在 root 擁有的測試目錄內檢查祖先，不等同測試
正式環境的整條 root 擁有路徑。腳本保留測試目錄供檢查，最後顯示精確的清理命令。
這不是正式安裝或驗收，也尚未測試 sudoers／SSH 完整入口。

## 候選入口相容性

`travel-deploy-entry.candidate` 是基於提供的正式入口所建立的完整候選檔；原本
停用的 `travel-deploy-entry` 並未啟用。`travel-deploy-control.candidate` 保留
原本 status-only 行為，`sudoers.candidate` 保留 status 規則並增加固定無參數
接收 wrapper。候選入口使用 Bash privileged mode，避免非互動式啟動讀取 BASH_ENV。

```bash
cd ~/travel-deploy-test/repo
bash deploy/server/test-entry-linux.sh "$PWD"
```

此測試檢查 Bash 與 sudoers 語法、既有四種操作、輸出、非法輸入、固定 wrapper
參數及環境注入。它只以替身模擬 sudo 端點，不會安裝 sudoers；因此不驗證真實
sudo 授權決策或 SSH daemon 配置，正式安裝前仍須於獨立 Linux 環境驗證。

先前 WSL 接收整合測試已由使用者執行並回報 `RECEIVER_INTEGRATION_OK`：涵蓋
manual／CI 成功、無效 gzip、摘要不符、空輸入、超量、逾時、重複快照、檔案
類型與鎖競爭，以及 nobody 存取限制。無效 gzip 的 Validator 錯誤為預期結果。
新增的候選入口測試尚待 WSL 執行；Python 3.10 語法靜態檢查不代表在 3.10 執行過。
# 安裝指引更新

本文件保留模組開發時的候選狀態；正式安裝請以 [INSTALL.md](INSTALL.md) 為準。

