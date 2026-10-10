"""日志包。"""

from spritelens.logs.local_logger import (
    get_logger,
    install_excepthook,
    setup_logger,
)

__all__ = ["get_logger", "install_excepthook", "setup_logger"]
