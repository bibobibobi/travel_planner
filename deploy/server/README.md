# 部署工具文件

正式安裝來源、權限與順序請以 [INSTALL.md](INSTALL.md) 為準。
各階段的實作與隔離測試紀錄見 [RECEIVER.md](RECEIVER.md)、
[RELEASE.md](RELEASE.md)、[DEPLOYMENT.md](DEPLOYMENT.md)、
[PIPELINE.md](PIPELINE.md)、[CD.md](CD.md) 與 [BACKUP.md](../maintenance/BACKUP.md)。

這些工具為候選版本，部署與備份共用 `/opt/travel-app/.lifecycle.lock`。
`.release-ready` 只代表建置完成；部署成功狀態另由控制器持久化。
未完成正式環境驗收前保持 CD 停用，不直接以 root 執行 Release 程式碼。
