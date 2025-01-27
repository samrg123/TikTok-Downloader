import os
import sys
import io
import threading

from collections.abc import Iterable

class ThreadedStdOut:

    _globalBuffers: dict[int, io.StringIO] = {}
    _globalBuffersLock = threading.RLock()
    _globalMainThreadId:int|None = None

    class BufferReference():
        def __enter__(self) -> io.StringIO:
            ThreadedStdOut._globalBuffersLock.acquire()
            
            threadId = threading.get_ident()
            if threadId in ThreadedStdOut._globalBuffers:
                return ThreadedStdOut._globalBuffers[threadId]

            buffer = io.StringIO()
            ThreadedStdOut._globalBuffers[threadId] = buffer
            return buffer
        

        def __exit__(self, type, value, traceback) -> None:
            ThreadedStdOut._globalBuffersLock.release()


    def write(self, s: str) -> int:
        with ThreadedStdOut.BufferReference() as buffer:
            result = buffer.write(s)
            self._update()
            return result
    
    def writelines(self, lines: Iterable[str]) -> None:
        with ThreadedStdOut.BufferReference() as buffer:
            result = buffer.writelines(lines)
            self._update()
            return result

    def read(self, size: int) -> str:
        with ThreadedStdOut.BufferReference() as buffer:
            return buffer.read(size)

    def readline(self, size: int = -1) -> str:
        with ThreadedStdOut.BufferReference() as buffer:
            return buffer.readline(size)

    def readlines(self, hint: int = -1) -> list[str]:
        with ThreadedStdOut.BufferReference() as buffer:
            return buffer.readlines(hint)

    def seek(self, cookie: int, whence: int = 0) -> int:
        with ThreadedStdOut.BufferReference() as buffer:
            return buffer.seek(cookie, whence)

    def __init__(self, header:str = "", stdout = sys.stdout) -> None:
        with ThreadedStdOut._globalBuffersLock:

            # TODO: Add support for nested ThreadedStdOut by making _globalMainThreadId and headers arrays
            #       And then somehow caching the mainId of the current buffers created in its context so
            #       we can pop them off _globalBuffers in __del__ 
            assert ThreadedStdOut._globalMainThreadId is None, f"Nested ThreadedStdOut is not supported"

            self.header = header
            self.stdout = stdout
            ThreadedStdOut._globalMainThreadId = threading.get_ident()

            self._update()
            

    def __del__(self) -> None:
        with ThreadedStdOut._globalBuffersLock:
            ThreadedStdOut._globalBuffers = {}
            ThreadedStdOut._globalMainThreadId = None


    def _update(self) -> None:
        numTermCols, numTermLines = os.get_terminal_size()

        # Go home, clear screen, and print header
        combinedBuffer = f"\x1B[H\x1B[J{self.header}"

        globalThreadIds = list(ThreadedStdOut._globalBuffers.keys())
        numThreadIds = len(globalThreadIds)
        
        # -2 for header and footer newlines
        availableLines = numTermLines - 2

        for i in range(0, numThreadIds if numThreadIds < availableLines else availableLines):

            threadId = globalThreadIds[i]
            buffer = ThreadedStdOut._globalBuffers[threadId]

            bufferContent = buffer.getvalue()
            bufferContentLen = len(bufferContent)

            # grab the last non-blank line to print
            prevNewLineIndex = bufferContentLen
            while True:
                newLineIndex = bufferContent.rfind("\n", 0, prevNewLineIndex)

                lineIndex = newLineIndex + 1
                strippedLine = bufferContent[lineIndex:prevNewLineIndex].strip()

                if lineIndex == 0 or len(strippedLine) > 0:
                    break

                prevNewLineIndex = newLineIndex
                
            # truncate buffer to last line to prevent memory overflow
            buffer.seek(0)
            buffer.truncate(0)
            buffer.write(bufferContent[lineIndex:])

            prefix = f"\n[{threadId:06}] {'>' if threadId == ThreadedStdOut._globalMainThreadId else '-'} "
            combinedBuffer+= f"{prefix}{strippedLine}"[:numTermCols]

        # add footer
        combinedBuffer+= "\n"
        if availableLines < numThreadIds:
            combinedBuffer+= "..."
        
        self.stdout.write(combinedBuffer)