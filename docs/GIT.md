# Git 工作区说明

用户指定远程为 https://github.com/AhsokaTano26/lean-observatory.git，分支 main。当前 Codex 环境将本目录的 .git 设为只读，因此 Git 元数据暂存在 /private/tmp/lean-observatory-deployment-git/.git，提交和正常快进推送从该工作目录完成。源码仍完整保存在当前项目目录。

GitHub 是持久交付位置；临时目录可能被系统清理。需要常规本地 Git 工作区时，在自己的普通终端将远程仓库 clone 到新的空目录，或调整当前环境对 .git 的写入权限。不要删除现有源码来建立仓库。

部署归档阶段，旧临时Git元数据已被清理。已用原始仓库归档及原签名提交载荷恢复浅工作副本，并核对父提交966c8f9与树2e654483完整SHA一致；后续仍使用本地git commit与正常快进git push，不改写远程历史。
