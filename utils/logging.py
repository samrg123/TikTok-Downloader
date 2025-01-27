from io import TextIOWrapper
import threading
import traceback
from datetime import datetime

from typing import Final
from dataclasses import dataclass, fields

@dataclass
class LogLevel:
    Disabled  : Final[int] = -1
    Error     : Final[int] = 0
    Default   : Final[int] = 1
    Verbose   : Final[int] = 2

    @staticmethod
    def getMapping() -> dict[str, int]:
        """Returns a dict LogLevel fields to values sorted in ascending value order"""
        mapping = {field.name: field.default for field in fields(LogLevel)}
        return dict(sorted(mapping.items(), key=lambda item: item[1]))

gLogLevel:int = LogLevel.Default
gLogFile:TextIOWrapper|None = None
gLogFileLock = threading.RLock()

def setLogFile(logFilePath:str) -> TextIOWrapper|None:
    """ Sets gLogFile to open a file at `logFilePath` and returns the previously set gLogFile
        If an empty string is provided the log file is disabled.
    """
    global gLogFile

    with gLogFileLock:

        oldLogFile = gLogFile
        if oldLogFile is not None:
            oldLogFile.close()

        if logFilePath:
            gLogFile = open(logFilePath, "w", errors="replace")
            gLogFile.reconfigure(
                write_through=True, # disable buffering 
                line_buffering=True # flush file at '\n' and thus each log message
            )
            
        log(f"Changed gLogFile from '{oldLogFile.name if oldLogFile else 'None'}' to '{logFilePath}'", logLevel=LogLevel.Verbose)

    return oldLogFile


def setLogLevel(level:int) -> int:
    """Sets gLogLevel to `level` and returns the previously set level"""

    global gLogLevel
    oldLevel = gLogLevel
    gLogLevel = level

    log(f"Changed gLogLevel from '{oldLevel}' to '{gLogLevel}'", logLevel=LogLevel.Verbose)

    return oldLevel


def log(msg, prefix:str="MSG", logLevel:int=LogLevel.Default) -> None:

    if gLogLevel >= logLevel:

        timeStr = datetime.now().strftime("%H:%M:%S:%f") 
    
        msgStart = f"{timeStr} -- {prefix}[{logLevel}]: "
        msgBody = str(msg).replace("\n", "\n"+" "*len(msgStart))    
    
        logStr = msgStart + msgBody + "\n"
        print(logStr, end="")

        # quick check to see if there is a log file
        if gLogFile is None:
            return

        # write to log file
        with gLogFileLock:

            # Note: we have to recheck gLogFile after we acquire the actual lock because it might have been unset on different thread
            if gLogFile is not None:
                gLogFile.write(logStr)

def panic(msg) -> None:
    gLogFileLock.acquire()

    with gLogFileLock:
        log(msg, "PANIC", logLevel=LogLevel.Error)
        traceback.print_stack(file=gLogFile)

    exit(1)

def warn(msg) -> None:
    log(msg, prefix="WARN", logLevel=LogLevel.Error)

def error(msg) -> None:
    log(msg, prefix="ERROR", logLevel=LogLevel.Error)    