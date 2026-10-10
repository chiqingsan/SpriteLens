"""转发到包内入口，保持仓库根目录启动习惯（python main.py）。"""

from spritelens.main import main

if __name__ == "__main__":
    raise SystemExit(main())
