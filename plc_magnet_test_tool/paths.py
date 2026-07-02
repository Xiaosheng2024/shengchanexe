import logging
import shutil
import sys
from pathlib import Path
from typing import Optional, Union


PathLike = Union[str, Path]


def get_base_dir(
    *,
    frozen: Optional[bool] = None,
    executable: Optional[PathLike] = None,
    module_file: Optional[PathLike] = None,
) -> Path:
    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if is_frozen:
        executable_path = Path(executable or sys.executable)
        return executable_path.resolve().parent
    source_path = Path(module_file or __file__)
    return source_path.resolve().parent


def get_resource_path(
    relative_path: PathLike,
    *,
    frozen: Optional[bool] = None,
    meipass: Optional[PathLike] = None,
    module_file: Optional[PathLike] = None,
) -> Path:
    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if is_frozen:
        resource_value = (
            meipass
            if meipass is not None
            else getattr(sys, "_MEIPASS", None)
        )
        if not resource_value:
            raise RuntimeError("无法定位程序内置资源目录。")
        resource_root = Path(resource_value)
    else:
        resource_root = get_base_dir(
            frozen=False,
            module_file=module_file,
        )
    return resource_root.resolve() / Path(relative_path)


def get_config_path(**base_dir_options) -> Path:
    return get_base_dir(**base_dir_options) / "config.ini"


def ensure_config_file(
    *,
    base_dir: Optional[PathLike] = None,
    resource_path: Optional[PathLike] = None,
) -> Path:
    target = (
        Path(base_dir).resolve() / "config.ini"
        if base_dir is not None
        else get_config_path()
    )
    if target.exists():
        return target

    source = (
        Path(resource_path).resolve()
        if resource_path is not None
        else get_resource_path("config.example.ini")
    )
    if not source.is_file():
        raise RuntimeError(
            "config.example.ini 未打包或不存在，无法创建配置文件。"
        )
    try:
        shutil.copyfile(source, target)
    except OSError as exc:
        raise RuntimeError(
            "无法创建配置文件，请检查程序目录权限。"
        ) from exc
    return target


def ensure_log_dir(*, base_dir: Optional[PathLike] = None) -> Path:
    root = (
        Path(base_dir).resolve()
        if base_dir is not None
        else get_base_dir()
    )
    log_dir = root / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            "无法创建日志目录，请检查程序目录权限。"
        ) from exc
    return log_dir


def configure_file_logging(
    *,
    base_dir: Optional[PathLike] = None,
) -> Path:
    log_path = ensure_log_dir(base_dir=base_dir) / "plc_magnet_test.log"
    try:
        handler = logging.FileHandler(
            log_path,
            encoding="utf-8",
        )
    except OSError as exc:
        raise RuntimeError(
            "无法创建日志文件，请检查程序目录权限。"
        ) from exc
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger = logging.getLogger("plc_magnet_test_tool")
    logger.setLevel(logging.INFO)
    if not any(
        isinstance(existing, logging.FileHandler)
        and Path(existing.baseFilename) == log_path
        for existing in logger.handlers
    ):
        logger.addHandler(handler)
    else:
        handler.close()
    return log_path
