# 第三方依赖

## mijiaAPI 4.4.0

- 项目：[Do1e/mijia-api](https://github.com/Do1e/mijia-api)
- 发布包：[PyPI mijiaAPI 4.4.0](https://pypi.org/project/mijiaAPI/4.4.0/)
- 许可证：GNU General Public License v3.0；发布包保留原许可证。
- 用途：米家扫码登录、账号凭据刷新、米家云设备及场景调用。
- 接入：通过依赖安装，不复制或修改上游发行包；插件适配层为上游请求补充超时和取消检查，并接管凭据持久化。
- 上游登录 API 中的 `_get_qr_login_data` / `_complete_qr_login` 是私有方法，因此固定依赖版本并通过适配测试约束升级。

上游 README 除 GPL-3.0 外，还写有“仅供学习交流使用，不得用于商业用途”的声明。
此个人预览版保留这一事实；商业使用或随产品公开分发前应向上游澄清额外声明，不能把本项目当成小米官方开放 API 授权。
插件对自身新增代码采用 GPL-3.0，完整文本见 `LICENSE`。

## 其他依赖

依赖版本见 `requirements.lock`。requests、urllib3、certifi、charset-normalizer、idna、
Pillow、qrcode、pycryptodome、tzlocal、tzdata、colorama 由安装器安装，保留各自包内的许可证。
未随安装包嵌入第三方依赖二进制。二维码使用 qrcode/Pillow 在本机生成。

米家认证协议内部的签名、加密与摘要由上游实现，是对接外部协议所需，不用于插件自身文件完整性或配置变更检测。
