import requests
import re
import asyncio
from bs4 import BeautifulSoup

def get_release_info(rym_url):
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'}
    response = requests.get(rym_url, headers=headers)

    soup = BeautifulSoup(response.content, "html.parser")

    release_title_elem = soup.find("div", {"class": "album_title"})
    try:
        artist_name = list(release_title_elem.find("span", {"class": "credited_name"}).children)[0] # this only works for collaborative albums
    except:
        release_title_artist = re.findall("(.+)\n +\nBy (.+)", release_title_elem.text)
    else:
        release_title_artist = [(re.findall("(.+)\n +\nBy .+", release_title_elem.text)[0], artist_name)]

    try:
        primary_genres = soup.find("span", {"class": "release_pri_genres"}).text
    except:
        primary_genres = None

    try:
        secondary_genres = soup.find("span", {"class": "release_sec_genres"}).text
    except:
        secondary_genres = None

    #alt_text = re.search('Cover art for (.*)"',response.text).group()[:-1]  # not using anymore
    release_cover_elem = soup.find("img")
    release_cover_url = "https:" + release_cover_elem["src"]
    if "https://e.snmc.io/3.0/img/blocked_art/enable_img_600x600.png" in release_cover_url:
        release_cover_url = None

    release_year_proto = re.findall(r"Released\w+ (\d+)|Released\d+ \w+ (\d+)|Released(\d{4})", soup.text)
    if release_year_proto:
        release_year = release_year_proto[0][0] or release_year_proto[0][1] or release_year_proto[0][2]
    else:
        release_year = None
    release_type = re.findall("Type(\w+)", soup.text)[0]

    return {
        "release_title": release_title_artist[0][0],
        "artist": release_title_artist[0][1],
        "primary_genres": primary_genres,
        "secondary_genres": secondary_genres,
        "release_cover_url": release_cover_url,
        "release_year": release_year,
        "release_type": release_type
    }

async def get_rating_from_review(user_reviews_url, release_url):
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'}
    response = requests.get(user_reviews_url, headers=headers)

    soup = BeautifulSoup(response.content, "html.parser")
    local_url = re.search("(\/release.+)", release_url).group()
    release_url_elem = soup.find("a", {"href": local_url})
    
    new_url = user_reviews_url + "/1"
    page_number = 1
    max_page = int(soup.find("a", {"class": "navlinknum"}).text)

    while not(release_url_elem):
        if page_number >= max_page:
            return None

        page_number += 1
        new_url = user_reviews_url + "/" + str(page_number)
        await asyncio.sleep(10)
        response = requests.get(new_url, headers=headers)

        soup = BeautifulSoup(response.content, "html.parser")
        release_url_elem = soup.find("a", {"href": local_url})

    review_rating = float(list(release_url_elem.parent.nextSibling.nextSibling.children)[2]["title"][:3]) # getting a float value (e.g. 5.0) out of a "title= '5.00 stars'" atrribute

    return review_rating