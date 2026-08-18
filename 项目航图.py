"""项目航图兼容入口。

实际实现位于 project_map 包中；保留这个文件是为了兼容原有启动方式和 PyInstaller 配置。
"""

from project_map.main import main


if __name__ == "__main__":
    main()
