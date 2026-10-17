"""透网 LucidMesh：把多厂商路由器配置转换成统一配置图。"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lmesh")
except PackageNotFoundError:  # 未安装时（例如直接从源码运行）
    __version__ = "0.0.0"
