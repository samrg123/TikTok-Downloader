import concurrent.futures
import os
import re
import requests
import urllib.parse

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from utils.io.ThreadedStdOut import ThreadedStdOut
from utils.logging import *

import xml.etree.ElementTree as ET 

def HumanReadableSize(size:int) -> str:
    for suffix in ["bytes", "KB", "MB", "GB", "TB", "PB"]:
        if size < 1024:
            return f"{size:.3f} {suffix}"
        size/= 1024 

class DownloadFile(dict):
    pass

class FileDownloader():
    
    kDownloadChunkSize = 1*1024*1024
    kDefaultSanitizeSymbol = ""

    @staticmethod
    def SanitizeName(name:str) -> str:
    
        illegalSymbols = {
            "<"  : "{",
            ">"  : "}",
            ":"  : ";",
            "\"" : "'",
            "/"  : "-",
            "\\" : "-",
            "|"  : ";",
            "?"  : FileDownloader.kDefaultSanitizeSymbol,
            "*"  : FileDownloader.kDefaultSanitizeSymbol,
        }
    
        sanitizedName = ""
        for c in name:            
            charCode = ord(c)

            if charCode < 32 or charCode > 126:
                sanitizedName+= FileDownloader.kDefaultSanitizeSymbol
            
            elif c in illegalSymbols:

                sanitizedName+= illegalSymbols[c]

            else:
                sanitizedName+= c

        # strip and replace runs of two or more spaces with single space
        sanitizedName = re.sub("( {2,})", " ", sanitizedName.strip())

        return sanitizedName

    @staticmethod
    def ParseXML(xml:ET) -> DownloadFile:
        
        downloadFile = DownloadFile()
        for fileXml in xml.findall("file"):

            fileName = fileXml.attrib["name"]
            fileUrl  = fileXml.attrib["url"]
            
            fileDir = os.path.dirname(fileName)
            fileBasename = os.path.basename(fileName)

            fileBase, fileExtension = os.path.splitext(fileBasename)

            sanitizedDir  = FileDownloader.SanitizeName(fileDir)
            sanitizedBase = FileDownloader.SanitizeName(fileBase)
            sanitizedName = os.path.join(sanitizedDir, sanitizedBase) + f"{fileExtension}"


            fileUrlSchemeEndIndex = fileUrl.find("://")
            if fileUrlSchemeEndIndex == -1:
                fileUrlSchemeEndIndex = 0
            else:
                fileUrlSchemeEndIndex+= 3

            fileUrlScheme = fileUrl[0:fileUrlSchemeEndIndex]
            fileURLPath = fileUrl[fileUrlSchemeEndIndex:]

            sanitizedUrl = fileUrlScheme + urllib.parse.quote(fileURLPath)

            if sanitizedName in downloadFile:
                warn(f"overwriting existing download [file:'{sanitizedName}' | url: '{downloadFile[sanitizedName]}'] url with: '{sanitizedUrl}'")

            downloadFile[sanitizedName] = sanitizedUrl

        return downloadFile

    @staticmethod
    def ParseFile(filePath:str) -> DownloadFile:
        return FileDownloader.ParseXML(ET.parse(filePath))
    
    @staticmethod
    def ParseStr(xmlStr) -> DownloadFile:
        return FileDownloader.ParseXML(ET.fromstring(xmlStr))    

    @staticmethod
    def ParseDir(dir:str) -> set[str]:        
        if not os.path.exists(dir):
            return set()
        
        files = set()
        for name in os.listdir(dir):
            fullPath = os.path.join(dir, name)

            if os.path.isdir(fullPath):
                files = files.union(FileDownloader.ParseDir(fullPath))   
            else:
                files.add(fullPath)

        return files

    @staticmethod
    def _DownloadThread(session:requests.Session, savePath:str, url:str) -> None|Exception:

        try:
            response = session.get(url, stream=True)
            response.raise_for_status()

            contentBytes = int(response.headers['Content-Length'])

            with open(savePath, "wb") as file:
            
                totalBytesWritten = 0
                for chunk in response.iter_content(chunk_size=FileDownloader.kDownloadChunkSize):
                    
                    chunkLen = len(chunk)
                    bytesWritten = file.write(chunk)

                    if bytesWritten != chunkLen:
                        raise Exception(f"Failed to write chunk to '{savePath}'. chunkLen: '{chunkLen}', bytesWritten: '{bytesWritten}'")

                    totalBytesWritten+= bytesWritten

                    percentComplete = totalBytesWritten / contentBytes 
                    print(f"--> '{savePath}': {100*percentComplete:.3f}% [{HumanReadableSize(totalBytesWritten)} / {HumanReadableSize(contentBytes)} ]")
        
        except Exception as e:
            log(f"Failed to download: '{url}' to '{savePath}'. Exception: '{e}' ", logLevel=LogLevel.Verbose)
            return e


    @staticmethod
    def Download(downloadFile: DownloadFile, dir:str = ".", numThreads:int=1, session:requests.Session = None) -> int:

        threadPool = ThreadPoolExecutor(max_workers=numThreads)
        downloadSession = requests.Session() if session is None else session 
        
        downloadFutures = []

        numDownloads = len(downloadFile)
        stdOutHeader = f"--- Downloading {numDownloads} files to '{dir}' (this may take some time) ---"
        with redirect_stdout(ThreadedStdOut(header=stdOutHeader)):
            
            for name, url in downloadFile.items():
                savePath = os.path.join(dir, name)
                saveDir = os.path.dirname(savePath)
                
                if not os.path.exists(saveDir):
                    os.makedirs(saveDir)
                    log(f"Created dir: '{saveDir}'", logLevel=LogLevel.Verbose)

                downloadFuture = threadPool.submit(FileDownloader._DownloadThread, session=downloadSession, savePath=savePath, url=url)
                downloadFutures.append(downloadFuture)

            
            print(f"Status: Waiting for download threads to finish...")
            exceptionList:list[Exception] = []
            for future in concurrent.futures.as_completed(downloadFutures):
            
                result = future.result()
                if(result is not None):
                    exceptionList.append(result)

        numExceptions = len(exceptionList)
        if numExceptions == 0:
            log(f"All {len(downloadFutures)} downloads completed successfully!")

        else:
            error(f"{numExceptions} exceptions occurred while downloading! | exceptionList: {exceptionList}")
        
        numSuccess = numDownloads - numExceptions
        return numSuccess