from .filesystem import FileSystemList, FileSystemRead, FileSystemWrite
from .shell import ShellRun
from .git_inspection import GitStatus, GitDiff
from .git_operations import GitCommit, GitPush
from .web_search import WebSearch

TOOLS = [
    FileSystemList(),
    FileSystemRead(),
    FileSystemWrite(),
    ShellRun(),
    GitStatus(),
    GitDiff(),
    GitCommit(),
    GitPush(),
    WebSearch(),
]