from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import json

import concurrent.futures
from time import sleep
import requests
from utils.ArgParser import *
from utils.parse import *
from utils.io.ThreadedStdOut import *
from utils.logging import *
from utils.FileDownloader import *

def tryProxy(session:requests.Session, proxy:str, timeout:float) -> requests.Session|None:

    proxyTestUrls = [
        # "http://google.com",
        # "https://google.com",
        "https://tiktok.com"
    ]

    proxyBannedStrings = [
        "geoblocking_page",
        "<title>error</title>"
    ]

    session = requests.Session()
    session.proxies.update({
        "http":  proxy,
        "https": proxy,
    })

    session.headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
    }

    try:
        for url in proxyTestUrls:
            log(f"Testing: {proxy} -> {url}")
            response = session.get(url, timeout=timeout)

            # test page for ban message
            for bannedString in proxyBannedStrings:
                if bannedString in response.text.lower():
                    raise Exception(f"Detected banned string '{bannedString}' in response to: '{url}'")

            log(f"Got proxy! | response: {response.text}")

        return session

    except Exception as e:
        log(f"{proxy} -> {url} failed with exception: {e}", logLevel=LogLevel.Verbose)

    return None

def getProxySession(session:requests.Session, preferredProxies:list[str], timeout:float) -> requests.Session|None:

    if(preferredProxies): 

        # try to connect to preferred proxies first
        for proxy in preferredProxies:
            session = tryProxy(proxy, timeout)

            if session is not None:
                return session


    # try a list of free proxies instead
    log(f"Exhausted preferred proxy list. Trying to connect to free proxy instead", logLevel=LogLevel.Verbose)
    response = requests.get("https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=protocolipport&format=text&anonymity=Elite&timeout=20000")
    proxyList = [ url.strip() for url in response.text.split("\n") ]

    if(proxyList):
        return getProxySession(proxyList)

    # failed to find working proxy
    return None


@dataclass
class DownloadResultType:
    DownloadedVideo   : Final[int] = 0
    DownloadedImage   : Final[int] = 1
    DownloadedBoth    : Final[int] = 2
    DownloadedNeither : Final[int] = 3 # Neither image or video post (can still download music and metadata)
    ParseError        : Final[int] = 4
    DownloadError     : Final[int] = 5
    NotAvailable      : Final[int] = 6
    Restricted        : Final[int] = 7
    Private           : Final[int] = 8
    ProxyError        : Final[int] = 9
    
    @staticmethod
    def NumTypes() -> int:
        return len(fields(DownloadResultType))

    @staticmethod
    def getMapping() -> dict[int, str]:
        mapping = {field.default: field.name for field in fields(DownloadResultType)}
        return dict(sorted(mapping.items()))


gSessionLock = threading.Lock()
gThreadSessions = {}

def getSession(preferredProxies:list[str]|None, proxyTimeout:float) -> requests.Session|None:

    with gSessionLock:

        # check for existing session
        threadId = threading.get_ident()
        if threadId in gThreadSessions:
            session = gThreadSessions[threadId]

        else:
        
            # create new session
            if preferredProxies is None:
                session = gThreadSessions[threadId] = requests.Session()

            else:
                session = getProxySession(preferredProxies, proxyTimeout)
                if session is not None:
                    gThreadSessions[threadId] = session

    return session



def downloadUrlThread_(url:str, preferredProxies:list[str]|None|None, proxyTimeout:float, downloadDir:str, maxRetries:int=5, retryTimeout:float=5) -> tuple[str, DownloadResultType]:
    print(f"Parsing: {url} for download link...")

    
    # Note: we initialize response to None because the very first session.get could throw an exception
    #       and thus response will not be defined
    response = None

    # Note: downloadFile is in format (url, savePath)
    downloadFiles:list[tuple[str, str]] = []
    try:

        session = getSession(preferredProxies, proxyTimeout)
        if session is None:
            error(f"Failed to get proxy session | preferredProxies: {preferredProxies} | proxyTimeout: {proxyTimeout}")
            return url, DownloadResultType.ProxyError

        # parse __UNIVERSAL_DATA_FOR_REHYDRATION__ script
        numRetries = 0
        while True:
            try:
                response = session.get(url)
                scriptSoup = parseHtmlElement(response.content, "script", {"id": "__UNIVERSAL_DATA_FOR_REHYDRATION__"})
                break

            except ParseException as e:
                if numRetries >= maxRetries:
                    error(f"Failed to parse script after {numRetries} retries! | exception: {e} | response: {response.content}")
                    return url, DownloadResultType.ParseError

            warn(f"[{numRetries+1}/{maxRetries}] Failed to parse script (blocked by captcha?). Sleeping for {retryTimeout} seconds and reattempting | url: {url} | response: {response.content}")
            sleep(retryTimeout)
            numRetries+= 1


        # parse script json
        scriptJson  = json.loads(scriptSoup.text.encode('ascii','xmlcharrefreplace'))
        detail = ParsableDictionary(scriptJson["__DEFAULT_SCOPE__"]["webapp.video-detail"])
        
        detailStatusCode = detail.parse("statusCode", int)

        if detailStatusCode in [10204, 100004, 10231]:
            log(f"Detected NoLongerAvailable for url: {url} | detail: {detail}", logLevel=LogLevel.Verbose)
            return url, DownloadResultType.NotAvailable

        if detailStatusCode == 10222:

            # TODO: enable logins to view private videos
            log(f"Detected private video for url: {url} | detail: {detail}", logLevel=LogLevel.Verbose)
            return url, DownloadResultType.Private

        if detailStatusCode != 0:
            error(f"Detected unknown status for url: {url} |  detail: {detail}")
            return url, DownloadResultType.ParseError


        itemInfo   = detail.parse("itemInfo", ParsableDictionary)
        itemStruct = itemInfo.parse("itemStruct",  ParsableDictionary)

        isClassified = itemStruct.parseDefault("isContentClassified", False)
        if isClassified:
            # TODO: allow us to log into tiktok and downloaded classified / age restricted videos  
            log(f"Detected classified content for url: {url} | detail: {detail}", logLevel=LogLevel.Verbose)
            return url, DownloadResultType.Restricted

        videoInfo  = itemStruct.parse("video",  ParsableDictionary)
        musicInfo  = itemStruct.parse("music",  ParsableDictionary)
        authorInfo = itemStruct.parse("author", ParsableDictionary)

        id            = parseStripedHtmlString(itemStruct.parse("id", str))
        timestamp     = itemStruct.parse("createTime", int)
        comments      = itemStruct.parse("comments", list[str])
        keywords      = itemStruct.parseDefault("suggestedWords", [])
        location      = parseStripedHtmlString(itemStruct.parse("locationCreated"))
        description   = parseStripedHtmlString(itemStruct.parse("desc"))
        
        userId        = parseStripedHtmlString(authorInfo.parse("uniqueId")) 
        userNickname  = parseStripedHtmlString(authorInfo.parse("nickname")) 
        userSignature = parseStripedHtmlString(authorInfo.parse("signature")) 
        
        musicUrl      = parseStripedHtmlString(musicInfo.parse("playUrl"))
        musicCoverUrl = parseStripedHtmlString(musicInfo.parse("coverLarge"))
        musicName     = parseStripedHtmlString(musicInfo.parse("title"))
        musicArtist   = parseStripedHtmlString(musicInfo.parseDefault("authorName", "N/A"))
        musicAlbum    = parseStripedHtmlString(musicInfo.parseDefault("album", "N/A"))


        # Note: userIds may contain only unclean symbols so we store all unrepresentable
        #       userIds in a common '_' folder
        sanitizedUserId = FileDownloader.SanitizeName(userId) or "_" 
        sanitizedDescription = FileDownloader.SanitizeName(description)
        sanitizedDescriptionId = f"{sanitizedDescription[:255-(len(id) + 3)]} - {id}" if sanitizedDescription else f"{id}"
        sanitizedSaveDir = f"{downloadDir}/{sanitizedUserId}/{sanitizedDescriptionId}"

        # add music to downloadFiles
        sanitizedMusicName = FileDownloader.SanitizeName(musicName) 
        sanitizedMusicSuffix = f" - {sanitizedMusicName}" if sanitizedMusicName else ""

        if musicUrl:
            downloadFiles.append( (musicUrl, f"{sanitizedSaveDir}/music{sanitizedMusicSuffix}.mp4") )
    
        if musicCoverUrl:
            downloadFiles.append( (musicCoverUrl, f"{sanitizedSaveDir}/music cover{sanitizedMusicSuffix}.jpeg") )


        resultType = DownloadResultType.DownloadedNeither
        
        videoPlayUrl = parseStripedHtmlString(videoInfo.parse("playAddr"))
        if videoPlayUrl:

            # Add video to downloadFiles 
            videoExtension = parseStripedHtmlString(videoInfo.parse("format"))
            downloadFiles.append( (videoPlayUrl, f"{sanitizedSaveDir}/video.{videoExtension}") )

            resultType = DownloadResultType.DownloadedVideo

        imagePost = itemStruct.parseDefault("imagePost", None, ParsableDictionary)
        if imagePost is not None:
            log(f"Detected photo for url: {url} | imagePost: {imagePost}", logLevel=LogLevel.Verbose)

            images = imagePost.parse("images", list[ParsableDictionary])
 
            # add image files to downloadFiles
            for i, image in enumerate(images):
 
                imageUrlDict = image.parse("imageURL", ParsableDictionary)
                imageUrls = imageUrlDict.parse("urlList", list[str])

                numImageUrls = len(imageUrls)
                if numImageUrls == 0:
                    error(f"Expected at least 1 imageUrl | imagePost: {imagePost}")
                    return url, DownloadResultType.ParseError

                if numImageUrls > 1:
                    log(f"Expected 1 image url, got {numImageUrls}. Ignoring others  | imageUrls: {imageUrls}", logLevel=LogLevel.Verbose)

                imageUrl = imageUrls[0]
                
                downloadFiles.append( (imageUrl, f"{sanitizedSaveDir}/{i}.jpeg") )

            resultType = DownloadResultType.DownloadedBoth if (resultType == DownloadResultType.DownloadedVideo) else DownloadResultType.DownloadedImage


        if resultType == DownloadResultType.DownloadedNeither:
            warn(f"Missing video and image post for url: {url} | itemStruct: {itemStruct}")


    except Exception as e:
        error(f"Error While Parsing: {url} | Exception: {e} | response: {'None' if response is None else response.content}")
        return url, DownloadResultType.ParseError

    # Make metadata file
    # Note: exist_ok to prevent a race condition with another thread
    os.makedirs(sanitizedSaveDir, exist_ok=True)
    
    print(f"Writing Metadata file for {url}")
    metaData = ""
    with open(f"{sanitizedSaveDir}/metadata.txt", "w", encoding="utf-8") as file:
        metaData+= f"Url:        {url}\n" 
        metaData+= f"Date:       {datetime.fromtimestamp(timestamp)}\n"
        metaData+= f"Location:   {location}\n"
        metaData+= f"Content ID: {id}\n"
        metaData+= f"\n"
        metaData+= f"UserId:    {userId}\n"
        metaData+= f"Nickname:  {userNickname}\n"
        metaData+= f"Signature: {{\n"
        metaData+= f"\t{userSignature.replace('\n', '\n\t')}\n"
        metaData+= f"}}\n"
        metaData+= f"\n"
        metaData+= f"Music:     {musicName}\n"
        metaData+= f"Artist:    {musicArtist}\n"
        metaData+= f"Album:     {musicAlbum}\n"
        metaData+= f"Music Url: {musicUrl}\n"
        metaData+= f"Cover Url: {musicCoverUrl}\n"
        metaData+= f"\n"
        metaData+= f"Keywords [{len(keywords)}] {{\n"
        metaData+= f"\t{'\n\t'.join(keywords)}\n"
        metaData+= f"}}\n"
        metaData+= f"\n"
        metaData+= f"Description {{\n"
        metaData+= f"\t{description.replace('\n', '\n\t')}\n"
        metaData+= f"}}\n"
        metaData+= f"\n"
        metaData+= f"Comments [{len(comments)}] {{\n"
        metaData+= f"\t{'\n\t'.join(comments)}\n"
        metaData+= f"}}\n"

        file.write(metaData)

    # download files
    downloadExceptions = []
    for downloadUrl, savePath in downloadFiles:
        downloadException = FileDownloader._DownloadThread(session=session, savePath=savePath, url=downloadUrl)
        if downloadException is not None:
            downloadExceptions.append(downloadException)

    numDownloadExceptions = len(downloadExceptions)
    if numDownloadExceptions > 0:
        error(f"Error While Downloading {numDownloadExceptions}/{len(downloadFiles)} for url: {url} | Exceptions: {downloadExceptions} | itemStruct: {itemStruct}")
        return url, DownloadResultType.DownloadError

    return url, resultType

class UrlDownloadResults:
    resultList:list[list[str]]

    def __init__(self):

        self.resultList = list()
        for _ in range(DownloadResultType.NumTypes()):
            self.resultList.append(list())

    def AddResult(self, url:str, type:DownloadResultType) -> None:
        self.resultList[int(type)].append(url) 

    def GetUrls(self, type:DownloadResultType) -> list[str]:
        return self.resultList[int(type)]
    
    def GetCount(self, type:DownloadResultType) -> list[str]:
        return len(self.resultList[int(type)])

    def __str__(self):

        result = ""
        numUrls = 0

        for field in fields(DownloadResultType):
            numType = len(self.resultList[field.default])

            result+= f" | {field.name}: {numType}"
            numUrls+= numType

        return f"Num Urls: {numUrls}{result}"

    def SaveToFile(self, filePath:str) -> None:
        with open(filePath, "w") as file:

            file.write(f"Result Summary - {self}\n\n")

            for field in fields(DownloadResultType):                
                fieldUrls = self.resultList[field.default]                
                file.write(f"{field.name} Urls [{len(fieldUrls)}]:\n\t{'\n\t'.join(fieldUrls)}\n\n")


def downloadUrls(urls:list[str], downloadDir:str, preferredProxies:list[str]|None, proxyTimeout:float, numThreads:int) -> UrlDownloadResults:    
    futures = []
    threadPool = ThreadPoolExecutor(max_workers=numThreads)
    
    numUrls = len(urls)
    results = UrlDownloadResults()

    stdOutHeader = f"--- Downloading {len(urls)} files to '{downloadDir}' (this may take some time) ---"
    with redirect_stdout(ThreadedStdOut(header=stdOutHeader)):

        for url in urls:
            downloadFuture = threadPool.submit(downloadUrlThread_, url=url, preferredProxies=preferredProxies, proxyTimeout=proxyTimeout, downloadDir=downloadDir)
            futures.append(downloadFuture)

        for i, future in enumerate(concurrent.futures.as_completed(futures)):

            print(f"Waiting for threads to finish - Progress: {i}/{numUrls} [{(100*i/numUrls):.2f}%] - Results: {results}")
            
            url, resultType = future.result() 
            results.AddResult(url, resultType)

    return results

def main():

    class MainArgs(Args):        
        file         = Arg(longName="--file",         metavar="str",        type=str,   default="./user_data_tiktok.json",  help=f"Specifies the tiktok user data json file to parse.")
        dir          = Arg(longName="--dir",          metavar="str",        type=str,   default="./DownloadedFiles",        help=f"Specifies the folder to download the files to.")
        threads      = Arg(longName="--threads",      metavar="int",        type=int,   default=max(32, os.cpu_count()),    help=f"Specifies the number of threads to use while downloading.")
        proxyTimeout = Arg(longName="--proxyTimeout", metavar="float",      type=float, default=5,                          help=f"Specified the default number of seconds to wait while attempting to connect to proxies.")
        proxy        = Arg(longName="--proxy",        metavar="list[str]",  type=str,   default=None,                       help=f"A comma separated list of preferred proxies to use. If no list is provided or all proxies fail then a free proxy from proxyscrape.com will be used.")
        log          = Arg(longName="--log",          metavar="str",        type=str,   default="",                         help=f"Specifies an log file to write to or blank for none.")
        verbose      = Arg(longName="--verbose",      metavar="int",        type=int,   default=LogLevel.Default,           help=f"Specifies the verbose log level. Larger values enable more verbose output. Log Levels: {LogLevel.getMapping()}")

    argParser = ArgParser(
        description = "A lightweight python utility for downloading liked and favorited videos specified in a tiktok json files"
    )

    args = argParser.Parse(MainArgs())

    setLogFile(args.log.value)
    setLogLevel(args.verbose.value)

    filePath     = args.file.value
    filePath     = args.file.value
    numThreads   = args.threads.value
    proxyList    = args.proxy.value
    proxyTimeout = args.proxyTimeout.value
    downloadDir  = args.dir.value

    preferredProxies = None if proxyList is None else proxyList.split(",")

    # process user data
    log(f"Reading {filePath}...")
    with open(filePath, "rb") as file:
        data = json.load(file)

    likedVideoList =  data["Activity"]["Like List"]["ItemFavoriteList"]
    likedVideoUrls = [likedVideoList[i]['link'] for i in range(0, len(likedVideoList))]

    favoriteVideoList = data["Activity"]["Favorite Videos"]["FavoriteVideoList"]
    favoriteVideoUrls = [favoriteVideoList[i]['Link'] for i in range(0, len(favoriteVideoList))]
    
    
    # download files
    log("Downloading Favorites...")
    favoriteResults = downloadUrls(favoriteVideoUrls, f"{downloadDir}/favoriteVideos", preferredProxies=preferredProxies, proxyTimeout=proxyTimeout, numThreads=numThreads)
    favoriteResults.SaveToFile(f"{downloadDir}/favoriteVideos.log")

    print("\n") 

    log(f"Downloading Likes...")
    likedResults = downloadUrls(likedVideoUrls, f"{downloadDir}/likedVideos", preferredProxies=preferredProxies, proxyTimeout=proxyTimeout, numThreads=numThreads)
    likedResults.SaveToFile(f"{downloadDir}/likedVideos.log")

    print("\n")

    log(f"Download Results:")
    log(f"Results [Favorite Videos] - {favoriteResults}")
    log(f"Results [Liked Videos]    - {likedResults}")

    print("\n")

if __name__ == "__main__":
    main()