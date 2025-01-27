# Welcome to the TikTok Downloader Repo!

**Table of contents:**
---
> 1. [About TikTok Downloader](#about)  
> 2. [Getting Started](#gettingStarted)
> 3. [Things To Note](#notes)
---


<a name="about"></a>
## About TikTok Downloader
TikTok Downloader is a lightweight python utility used to bulk download liked and favorite video and image posts from TikTok.

 

<a name="gettingStarted"></a>
## Getting Started

First [request a copy of your user data from TikTok](https://support.tiktok.com/en/account-and-privacy/personalized-ads-and-data/requesting-your-data#1).

Next clone the repo and install the required python packages:
```bash
git clone https://github.com/samrg123/TikTok-Downloader.git
cd ./TikTok-Downloader
pip install -r ./requirements.txt
```


Then execute the program according to your needs:
```bash
usage: TikTokDownloader.py [-h] [--dir str] [--file str] [--log str] [--proxy list[str]] [--proxyTimeout float] [--threads int] [--verbose int]

A lightweight python utility for downloading liked and favorited videos specified in a tiktok json files

options:
  -h, --help            show this help message and exit
  --dir str             Specifies the folder to download the files to. Default [str] = './DownloadedFiles'
  --file str            Specifies the tiktok user data json file to parse. Default [str] = './user_data_tiktok.json'
  --log str             Specifies an log file to write to or blank for none. Default [str] = ''
  --proxy list[str]     A comma separated list of preferred proxies to use. If no list is provided or all proxies fail then a free proxy from proxyscrape.com will be used.
  --proxyTimeout float  Specified the default number of seconds to wait while attempting to connect to proxies. Default [float] = '5'
  --threads int         Specifies the number of threads to use while downloading. Default [int] = '32'
  --verbose int         Specifies the verbose log level. Larger values enable more verbose output. Log Levels: {'Disabled': -1, 'Error': 0, 'Default': 1, 'Verbose': 2} Default [int] = '1'
```

<a name="notes"></a>
## Things to Note
- As of now, TikTok limits the number of liked and favorite posts reported in 'user_data.json' each to 4999 items.
- Make sure you have enough disk space to complete the download. For an estimate ~7000 posts requires ~100GB of disk space.
- TikTok Downloader doesn't log into your account and therefore is unable to download confidential or private posts shared with you. These posts will be reported in 'likedVideos.log' and 'favoriteVideos.log' so you can optionally download them manually.
- The downloader was created in very short notice in response to the [2025 TikTok Shutdown in the US](https://en.wikipedia.org/wiki/Restrictions_on_TikTok_in_the_United_States#2025_shutdown) and as a result implements a minimum number of features to satisfy my needs. Please feel free to contact me if you'd like me extend the utility to support new features such as downloading all the videos for a specific user, or support logging into accounts to download private videos.