from .filesystem import FileSystemList, FileSystemRead, FileSystemWrite
from .shell import ShellRun
from .git_inspection import GitStatus, GitDiff
from .git_operations import GitCommit, GitPush
from .code_edit import CodeEdit
from .test_runner import TestRunner

ALL_TOOLS = [
    FileSystemList(),
    FileSystemRead(),
    FileSystemWrite(),
    ShellRun(),
    GitStatus(),
    GitDiff(),
    GitCommit(),
    GitPush(),
    CodeEdit(),
    TestRunner(),
]

__all__ = ["ALL_TOOLS"]