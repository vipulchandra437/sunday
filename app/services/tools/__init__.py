from .filesystem import FileSystemList, FileSystemRead, FileSystemWrite
from .shell import ShellRun
from .git_inspection import GitStatus, GitDiff

TOOLS = [
    FileSystemList(),
    FileSystemRead(),
    FileSystemWrite(),
    ShellRun(),
    GitStatus(),
    GitDiff(),
]