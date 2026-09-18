from .filesystem import FileSystemList, FileSystemRead, FileSystemWrite
from .shell import ShellRun
from .git_inspection import GitStatus, GitDiff
from .git_operations import GitCommit, GitPush

ALL_TOOLS = [
    FileSystemList(),
    FileSystemRead(),
    FileSystemWrite(),
    ShellRun(),
    GitStatus(),
    GitDiff(),
    GitCommit(),
    GitPush(),
]

__all__ = ["ALL_TOOLS"]