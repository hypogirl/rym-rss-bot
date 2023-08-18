import requests
import re
import asyncio
import json
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
    
    try:
        if release_cover_elem["alt"].startswith("Cover art for ") and "https://e.snmc.io/3.0/img/blocked_art/enable_img_600x600.png" not in release_cover_elem["src"]:
            release_cover_url = "https:" + release_cover_elem["src"]
        else:
            release_cover_url = None
    except KeyError:
        release_cover_url = None
    

    release_year_proto = re.findall(r"Released\w+ (\d+)|Released\d+ \w+ (\d+)|Released(\d{4})", soup.text)
    if release_year_proto:
        release_year = release_year_proto[0][0] or release_year_proto[0][1] or release_year_proto[0][2]
    else:
        release_year = None
    release_type = re.findall("Type(\w+)", soup.text)[0]

    release_links_elem = soup.find("div", {"id": "media_link_button_container_top"})
    if release_links_elem:
        release_links = json.loads(release_links_elem["data-links"])
    else:
        release_links = None

    return {
        "release_title": release_title_artist[0][0],
        "artist": release_title_artist[0][1],
        "primary_genres": primary_genres,
        "secondary_genres": secondary_genres,
        "release_cover_url": release_cover_url,
        "release_year": release_year,
        "release_type": release_type,
        "release_links": release_links
    }

async def get_rating_from_review(rym_user, release_url):
    user_reviews_url = f"https://rateyourmusic.com/collection/{rym_user}/reviews,ss.dd"
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'}
    response = requests.get(user_reviews_url, headers=headers)

    soup = BeautifulSoup(response.content, "html.parser")
    local_url = re.search("(\/release.+)", release_url).group()
    release_url_elem = soup.find("a", {"href": local_url})
    
    try:
        max_page = int(soup.find("a", {"class": "navlinknum"}).text)
    except AttributeError:
        pass
    else:
        new_url = user_reviews_url + "/1"
        page_number = 1

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