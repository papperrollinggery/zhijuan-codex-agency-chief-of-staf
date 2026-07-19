# Repository Self-Maintenance Mode

当当前 Git 根目录是本仓库时，默认任务是维护 Agency Chief of Staff Skill 的源码，而不是运行已安装的 Skill。

- 源码维护不得调用已安装的 `$agency-chief-of-staff` 或 `$zhijuan-codex-agency-chief-of-staf`。
- 不得用本 Skill 为源码维护创建 Agency Task、Codex Task/Thread、Receipt、Team Plan、Cold Review 或 Supervisor 流程。
- 只有隔离测试 fixture、临时目录、Model Smoke 或 Native Task/Thread Smoke 可以运行 Runtime 行为。
- 使用普通 Git、Python、单元测试和集成测试完成读取、修改与验证；保留用户已有改动，不修改用户全局 Codex 或 Skill 安装。
- 本文件不得加入 Runtime Bundle，不得被安装器复制，也不得作为正式 Skill 的激活、隐式路由或岗位注入机制。
