"""
Audison CLI 入口桥接文件。

pyproject.toml 入口点为 audison = "audison.cli:main"
实际 CLI 实现位于 cli/ 子包中。
此文件作为入口桥接，委托给 cli/__init__.py:main()。
"""

import importlib.machinery
import os


def main():
    """委托到 cli 子包的真实 main 函数。"""
    loader = importlib.machinery.SourceFileLoader(
        "audison._cli_entry",
        os.path.join(os.path.dirname(__file__), "cli", "__init__.py"),
    )
    _mod = loader.load_module()
    _mod.main()


if __name__ == "__main__":
    main()
