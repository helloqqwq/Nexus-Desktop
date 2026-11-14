# 第三方组件声明 / Third-Party Notices

Nexus 的源代码以 MIT 许可证发布（见 [LICENSE](LICENSE)）。官方安装包内含以下第三方组件，它们各自遵循自己的许可证。各项目的完整许可证文本可在其官方仓库或安装包内找到。

## Python 运行时依赖

| 组件 | 版本 | 许可证 |
| --- | --- | --- |
| [pywebview](https://github.com/r0x0r/pywebview) | 6.1 | BSD-3-Clause |
| [pythonnet](https://github.com/pythonnet/pythonnet) | 3.0.5 | MIT |
| [Pillow](https://python-pillow.org/) | 12.3.0 | MIT-CMU |
| [beautifulsoup4](https://www.crummy.com/software/BeautifulSoup/) | 4.14.3 | MIT |
| [comtypes](https://github.com/enthought/comtypes) | 1.4.16 | MIT |
| [cryptography](https://github.com/pyca/cryptography) | 43.0.3 | Apache-2.0 OR BSD-3-Clause |
| [python-docx](https://github.com/python-openxml/python-docx) | 1.2.0 | MIT |
| [numpy](https://numpy.org/) | 2.4.4 | BSD-3-Clause（含 0BSD / MIT / Zlib / CC0 片段） |
| [openpyxl](https://openpyxl.readthedocs.io/) | 3.1.5 | MIT |
| [python-pptx](https://github.com/scanny/python-pptx) | 1.0.2 | MIT |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2)（含 PDFium） | 5.11.0 | Apache-2.0 OR BSD-3-Clause；PDFium 为 BSD-3-Clause |
| [pystray](https://github.com/moses-palmer/pystray) | 0.19.5 | LGPL-3.0 |
| [pywin32](https://github.com/mhammond/pywin32) | 311 | PSF-2.0 |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | 2.0.1 | Apache-2.0 |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) | 0.5.5 | MIT |
| [uiautomation](https://github.com/yinkaisheng/Python-UIAutomation-for-Windows) | 2.0.29 | Apache-2.0 |
| [pywinpty](https://github.com/andfoy/pywinpty) | 3.1.2 | MIT |

### LGPL 组件说明（pystray）

`pystray` 以未修改的原始库形式随安装包分发，未做任何静态链接或修改。它的完整许可证文本随包提供；如需替换为其他版本或自行编译的版本，可用 `pip install pystray==0.19.5` 安装后重新执行 `python build\build_release.py`。

## 前端静态资源

| 资源 | 位置 | 许可证 |
| --- | --- | --- |
| [xterm.js](https://github.com/xtermjs/xterm.js) | `app/web/assets/vendor/xterm.js`、`xterm.css` | MIT |
| [@xterm/addon-fit](https://github.com/xtermjs/xterm.js) | `app/web/assets/vendor/addon-fit.js` | MIT |
| [JetBrains Mono](https://www.jetbrains.com/lp/mono/) | `app/web/assets/vendor/fonts/` | SIL Open Font License 1.1 |

## 商标与厂商图标

`app/web/assets/providers/` 与 `site/assets/providers/` 中的各模型厂商图标，其版权与商标归对应公司所有。Nexus 仅在界面中用它标识用户所配置的模型服务，不表示任何隶属、合作或背书关系。这些图标不在 MIT 许可证覆盖范围内。

## 系统组件

- **Microsoft Edge WebView2 Runtime**：Nexus 使用系统已安装的 WebView2 运行时渲染界面，不随安装包分发。
- **NSIS**：仅用于构建安装包，不随程序分发。
