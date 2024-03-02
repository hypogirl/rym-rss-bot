import asyncio
import math
import json
import pickle
import lzma
import re
import traceback
from datetime import datetime, timedelta
import discord
from discord.ext import commands
import xml.etree.ElementTree as ET
import vars
import requests
import rympy
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
import googleapiclient
import shutil
import pylast
from PIL import Image, ImageDraw, ImageFont
import io

global users, last, active_id, last_url, rate_limit
last = None
active_id = None
users = dict()
cache = dict()
date_format = "%a, %d %b %Y %H:%M:%S %z"
rate_limit = False

with open('users.json') as users_json:
    users = json.load(users_json)

with lzma.open('cache.lzma', 'rb') as file:
    cache = pickle.load(file)
    if cache.get("simple_releases"):
        for release in cache.get("simple_releases"):
            if release in cache.get("releases"):
                cache["simple_releases"].pop(release)

def get_current_time_text():
    now = datetime.now()
    current_time = now.strftime("%H:%M:%S")
    return "[" + current_time + "]"

def google_search(search_term, search_type="searchTypeUndefined"):
    service = build("customsearch", "v1", developerKey=vars.google_api_key)
    service_2 = build("customsearch", "v1", developerKey=vars.google_api_key_2)
    try:
        res = service.cse().list(q=search_term, cx=vars.cse_id, searchType=search_type, num=1).execute()
    except googleapiclient.errors.HttpError:
        try:
            res = service.cse().siterestrict().list(q=search_term, cx=vars.cse_id, searchType=search_type, num=1).execute()
        except googleapiclient.errors.HttpError:
            try:
                res = service_2.cse().list(q=search_term, cx=vars.cse_id, searchType=search_type, num=1).execute()
            except googleapiclient.errors.HttpError:
                res = service_2.cse().siterestrict().list(q=search_term, cx=vars.cse_id, searchType=search_type, num=1).execute()
    return res['items']

def get_release_info_from_google(url):
    result = google_search(url)[0]
    release_info = dict()
    if result['pagemap'].get('cse_image'):
        release_info["cover_url"] = result['pagemap']['cse_image'][0]['src']
    release_info["average_rating"] = float(result['pagemap']['aggregaterating'][0]['ratingvalue'])
    release_info["number_of_ratings"] = int(result['pagemap']['aggregaterating'][0]['ratingcount'])
    if year_position := re.search(r"(\d+) in the best albums of", result["pagemap"]["metatags"][0]['og:description']):
        release_info["year_position"] = int(year_position.group(1))
    if overall_position := re.search(r"(\d+) of all time", result["pagemap"]["metatags"][0]['og:description']):
        release_info["overall_position"] = int(overall_position.group(1))
    if primary_genres := re.search(r"Genres: ([^.]+)", result["pagemap"]["metatags"][0]['og:description']):
        release_info["primary_genres"] = primary_genres.group(1)
    if album_title := re.search(r"^(.+), an? ", result["pagemap"]["metatags"][0]['og:description']):
        release_info["title"] = album_title.group(1)
    if artist_name := re.search(r"by (.+) -", result["pagemap"]["metatags"][0]['og:title']):
        release_info["artist_name"] = artist_name.group(1)
    if release_type := re.search(r", an? +([\w ]+) by ", result["pagemap"]["metatags"][0]['og:description']):
        release_info["release_type"] = release_type.group(1)
    elif release_type := re.search(r", an? +([\w+ ]+)(?! by )\.", result["pagemap"]["metatags"][0]['og:description']):
        release_info["release_type"] = release_type.group(1)
    if year := re.search(r"Released .+ (\d{4}) on", result["pagemap"]["metatags"][0]['og:description']):
        release_info["year"] = year.group(1)
    elif year := re.search(r"Released .+ (\d{4}).", result["pagemap"]["metatags"][0]['og:description']):
        release_info["year"] = year.group(1)
    release_info['url'] = result['link']
    if date_match := re.search(r"Released (?:in )?(.*\d{4}) on", result['snippet']):
        date_text = date_match.group(1)
        date_components_count = date_text.count(" ") + 1
        date_formating = {1: "%Y",
                        2: "%B %Y",
                        3: "%d %B %Y"}
        release_info["release_date"] = datetime.strptime(date_text, date_formating[date_components_count])
    return release_info

def get_artist_info_from_google(url):
    result = google_search(url)[0]
    artist_info = dict()
    artist_info['url'] = result['link']
    if genres := re.search(r"Genres: ([^.]+)", result["pagemap"]["metatags"][0]['og:description']):
        artist_info['genres'] = genres.group(1)
    return artist_info

def get_review(description_elem):
    if review_elem := description_elem.find('span'):
        return review_elem.text.strip()
    else:
        return None

def parse_ratings(rym_user):
    url = f"https://rateyourmusic.com/~{rym_user}/data/rss"
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'}
    rss_response = requests.get(url, headers=headers) # get request using a browser header to avoid a RYM ban
    if rss_response.status_code == 503:
        return None
    print(get_current_time_text(), "Parsing ratings...")
    parsed_xml = ET.fromstring(rss_response.content)
    children = parsed_xml[0]
    ratings = [(rating[0].text, rating[1].text, get_review(rating[2]), rating[3].text) for rating in children if rating.tag == "item" and "/list/" not in rating[1].text]  # ratings and reviews have the
                                                                                                                                    # <item> tag so i'm filtering
                                                                                                                                    # through the useful information
    return ratings

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

async def get_recent_info(member, rym_user, last_tmp, feed_channel, user_id):
    ratings = parse_ratings(rym_user)
    try:
        print(get_current_time_text(), f"{member.display_name} ({rym_user}) parsed.")
    except AttributeError:
        await feed_channel.send(f"<@{user_id}> is not in the server anymore")

    global users, last, active_id, last_url, cache

    last = last_tmp
    active_id = str(member.id)

    i = 0
    users[active_id]["last"] = ratings[0][3]

    user_ratings = list()
    rating_counter = 0
    for (text, rym_url, review, timestamp) in ratings:
        rating_counter += 1
        if datetime.strptime(timestamp, date_format) <= datetime.strptime(last, date_format) or rating_counter >= 15:
            break

        i += 1

        if rym_url.startswith("https://rateyourmusic.com/film/"):
            continue

        text_info = re.findall(r"(Rated) .* (\d\.\d) star|(Reviewed)", text)   # text_info will be a list with a structure similar to the following two:
                                                                                # ["Rated", "2.5", ""] in case it's a rating
                                                                                # ["", "", "Reviewed"] in case it's a review

        if datetime.strptime(timestamp, date_format) <= datetime.strptime(last, date_format):
            break
        print(get_current_time_text(), rym_url)
        
        last_url = rym_url
        if cache.get("releases") and rym_url in cache["releases"]:
            release = cache["releases"][rym_url]
            try:
                googled_release_info = get_release_info_from_google(release.title + " " + release.artist_name)
                if googled_release_info["number_of_ratings"] > release.number_of_ratings:
                    print("Updated rating.", release.average_rating, "->", googled_release_info["average_rating"])
                    release.number_of_ratings = googled_release_info["number_of_ratings"]
                    release.average_rating = googled_release_info["average_rating"]
                    if not release.cover_url and googled_release_info.get("cover_url"):
                        release.cover_url = googled_release_info["cover_url"]
                    if googled_release_info.get("year_position"):
                        print("Updated year position.", release.year_position, "->", googled_release_info["year_position"])
                        release.year_position = googled_release_info["year_position"]
                    if googled_release_info.get("overall_position"):
                        print("Updated overall position.", release.overall_position, "->", googled_release_info["overall_position"])
                        release.overall_position = googled_release_info["overall_position"]
            except KeyError:
                print(rym_url, "not found on google")

        else:
            await asyncio.sleep(61)
            release = rympy.Release(rym_url)
            if not cache.get("releases"):
                cache["releases"] = dict()
            cache["releases"][rym_url] = release

        if text_info[0][0]:
            rating = float(text_info[0][1])
            rated_text = "rated"
            review = str()
        else:
            rating = await get_rating_from_review(rym_user, rym_url)

            if rating:
               rated_text = "rated and reviewed"
            else:
                rated_text = "reviewed" 
            
            if review:
                review = "--------------\n" + review
            else:
                review = str()
                rated_text = "rated"

        if not cache.get("users"):
                cache["users"] = dict()
        if str(member.id) not in cache["users"]:
            cache["users"][str(member.id)] = rympy.SimpleUser(username=users[str(member.id)]["rym"])

        cache["users"][str(member.id)].add_rating(rympy.Rating(id=release.id,
                    last_name=release.artist_name,
                    title=release.title,
                    release_year=release.release_date.year if release.release_date else None,
                    rating=rating,
                    review=review,
                    url=release.url,
                    release=release))

        if rating:
            star_rating = "<:star:1135605958333186149>" * int(rating) + "<:half:1135605972564455434> "  * (1 if rating != int(rating) else 0) # this simply makes a string with star (and half star) emojis corresponding to the user's rating
        else:
            star_rating = str()

        date = re.search(r"\d{1,2} \w{3}", timestamp).group() # getting the day and month

        primary_genres = str()
        if release.primary_genres:
            primary_genres = ", ".join([genre.name for genre in release.primary_genres])

        secondary_genres = str()
        if release.secondary_genres:
            secondary_genres = "*" + ", ".join([genre.name for genre in release.secondary_genres]) + "*"
        
        average_rating_str = str()
        if release.average_rating:
            average_rating_str = f"**{release.average_rating}** / 5.0 from {release.number_of_ratings} {'ratings' if release.number_of_ratings > 1 else 'rating'}\n\n"

        position_str = str()
        if release.release_date and release.year_position:
            position_str = f"**#{release.year_position}** for [{release.release_date.year}](https://rateyourmusic.com/charts/top/{release.type.split(',')[0].lower()}/{release.release_date.year}/{math.ceil(release.year_position/40)}/#pos{release.year_position})"
            if release.overall_position:
                position_str += f", **#{release.overall_position}** [overall](https://rateyourmusic.com/charts/top/{release.type.split(',')[0].lower()}/all-time/deweight:live,archival,soundtrack/{math.ceil(release.overall_position/40)}/#pos{release.overall_position})"
            position_str += "\n"
            
        body_text = f"{position_str}{average_rating_str}{primary_genres}\n{secondary_genres}\n\n**{date}** {star_rating}\n{review}"
        avatar_url = member.avatar.url if member.avatar else "https://e.snmc.io/3.0/img/logo/sonemic-32.png"
        user_url = f"https://rateyourmusic.com/~{rym_user}"

        rated_text += (' an ' if release.type in ['Album', 'EP'] else ' a ') + release.type
        if release.release_date and release.release_date.year:
            release_year = f"({release.release_date.year})"
        else:
            release_year = str()

        rating_info = {
            "title": f"{release.artist_name} - {release.title} {release_year}",
            "description": body_text,
            "url": rym_url,
            "author": f"{member.display_name} {rated_text}",
            "icon_url": avatar_url,
            "user_url": user_url,
            "thumbnail_url": release.cover_url,
            "streaming_links": release.links
        }

        
        one_month_ago = datetime.now() - timedelta(days=30)
        line_colour = 0x2d5ea9
        if release.release_date and release.release_date > one_month_ago:
            line_colour = 0x00df0d
        if release.is_bolded:
            line_colour = 0x339a6d
        if "LGBT" in release.descriptors:
            line_colour = 0xdc36b5
        if release.average_rating <= 2.5:
            line_colour = 0xe4101a
        if release.overall_position and release.overall_position <= 250:
            line_colour = 0xf9b505
        if release.is_nazi:
            line_colour = 0x2b2d31

        rating_embed = discord.Embed(title=rating_info['title'][:255], description=rating_info['description'], color= line_colour, url=rating_info['url'])
        rating_embed.set_author(name=rating_info['author'], icon_url=rating_info['icon_url'], url=rating_info['user_url'])

        if rating_info['thumbnail_url']:
            rating_embed.set_thumbnail(url=rating_info['thumbnail_url'])

        button_list = list()

        if release.links.spotify:
            button_list.append((release.links.spotify, "<:sp:1141025089878499389>"))

        if release.links.youtube:
            button_list.append((release.links.youtube, "<:yc:1140967863931392040>"))

        if release.links.bandcamp:
            button_list.append((release.links.bandcamp, "<:bc:1140967203596927017>"))

        if release.links.soundcloud:
            button_list.append((release.links.soundcloud, "<:sc:1140968078746857492>"))

        if release.links.apple_music:
            button_list.append((release.links.apple_music, "<:ac:1140967868708696104>"))


        button_list = button_list[:3]

        if not(last):
            break

        user_ratings.append((datetime.strptime(timestamp, date_format), rating_embed, button_list))
    
    print("\n")
    
    return ratings[0][3], user_ratings

def main():
    intents = discord.Intents.all()
    bot = commands.Bot(command_prefix= vars.command_prefix, intents= intents)
    lfm_network = pylast.LastFMNetwork(api_key=vars.lfm_key, api_secret=vars.lfm_secret)

    @bot.event
    async def on_ready():
        global users, last_url
        print(f'Logged in as {bot.user}.\n')
        
        feed_channel = bot.get_channel(vars.channel_id)
        await asyncio.sleep(int(input("Minutes: "))*60)
        while True:
            print(get_current_time_text(), "Starting...")
            global ratings
            ratings = list()
            for user_id in users:
                member = bot.get_guild(vars.guild_id).get_member(int(user_id))

                try:
                    await asyncio.sleep(61)
                    last, user_ratings = await get_recent_info(member, users[user_id]["rym"], users[user_id]["last"], feed_channel, user_id)
                    ratings += user_ratings
                except ET.ParseError:
                    await feed_channel.send(f"RYM rate limit. <@{vars.whitelisted_ids[-1]}>")
                    await asyncio.sleep(15 * 60)
                    last, user_ratings = await get_recent_info(member, users[user_id]["rym"], users[user_id]["last"], feed_channel, user_id)
                    users[user_id]["last"] = last
                except:
                    with open("error.log", "a") as error_file:
                        error_file.write(last_url + "\n" + traceback.format_exc() + "\n\n")
                    await feed_channel.send(f"Error found while getting rating data. Check log file. <@{vars.whitelisted_ids[-1]}>")
                else:
                    users[user_id]["last"] = last
            
            global cache
            with lzma.open('cache_tmp.lzma', 'wb') as file:
                pickle.dump(cache, file)

            print(get_current_time_text(), "Sending ratings...")
            for i, (_, embed, button_list) in enumerate(sorted(ratings, key=lambda x: x[0])):
                if not math.floor(i % (len(ratings)/5)):
                    full_percentage = math.floor(i/len(ratings)*100)
                    print("█"* int(full_percentage/10) + "_" * int((10 - int(full_percentage/10))) + "|", f"{full_percentage} %")
                try:
                    links_view = discord.ui.View(timeout= None)
                    for button in button_list:
                        links_view.add_item(discord.ui.Button(url= button[0], emoji= discord.PartialEmoji.from_str(button[1])))
                    await feed_channel.send(embed=embed, view=links_view)
                    await asyncio.sleep(120)
                except:
                    with open("error.log", "a") as error_file:
                        error_file.write(embed.title + "\n" + embed.description + "\n" + traceback.format_exc() + "\n\n")
                    await feed_channel.send(f"Error found while sending rating data to this channel. Check log file. <@{vars.whitelisted_ids[-1]}>")
            print("██████████| 100%")

            with open('users.json', 'w') as users_json:
                users_json.write(json.dumps(users, indent=2))

            print(get_current_time_text(), f"sleeping for {vars.sleep_minutes} minutes\n\n")
            await asyncio.sleep(vars.sleep_minutes * 60)

    @bot.event
    async def on_message(message):
        if message.author == bot.user:
            return
        
        if message.content.startswith("$"):
            await bot.process_commands(message)
            return
        
        '''if message.author.id == 356268235697553409 and message.embeds:
            single_embed = message.embeds[0]
            if "WhoKnows artist" in single_embed.footer.text:
                artist_info = get_artist_info_from_google(single_embed.title.split(" in ")[0])
                footer_text_split = single_embed.footer.text.split("\n")
                if len(footer_text_split) == 1:
                    single_embed.footer.text = f'RYM genres: {artist_info["genres"].lower().replace(",", " -")}\n{footer_text_split[0]}'
'''

    async def gen_add(rym_user, user_id, sendable):
        global users

        ratings = parse_ratings(rym_user)
        last = ratings[0][3] if ratings[0][3] else None

        users[user_id] = {
            "rym": rym_user,
            "last": last
            }
        
        with open('users.json', 'w') as users_json:
            users_json.write(json.dumps(users, indent=2))

        await sendable.send(f"<@{user_id}> (RYM username: **{rym_user}**) has been successfully added to the bot.")

    @bot.command()
    async def add(ctx, *, arg):
        if vars.admin_role_name not in [role.name for role in ctx.author.roles] and ctx.author.id not in vars.whitelisted_ids:
            return

        discord_rym_user = re.findall(r"(<@(\d+)>|\d+) +(\w+)", arg)
        user_id = discord_rym_user[0][1]
        rym_user = discord_rym_user[0][2]

        global cache
        if not cache.get("users"):
            cache["users"] = dict()
        cache["users"][user_id] = rympy.SimpleUser(username=rym_user)

        with lzma.open('cache_tmp.lzma', 'wb') as file:
            pickle.dump(cache, file)

        shutil.copy2("cache_tmp.lzma", "cache.lzma")

        await gen_add(rym_user, user_id, ctx)

    #@tree.command(name = "add")
    #async def slash_add(interaction, discord_user: str, rym_user: str):
    #    user_id = re.search(r"\d+", discord_user).group()

    @bot.command()
    async def remove(ctx, *, arg):
        if vars.admin_role_name not in [role.name for role in ctx.author.roles] and ctx.author.id not in vars.whitelisted_ids:
            return
        
        global users
        user_id = re.search(r"<@(\d+)>|(\d+)", arg).group()
        rym_user = users[user_id]["rym"]
        if user_id not in users:
            await ctx.send(f"This user is not connected to the bot.")
            return
        users.pop(user_id)

        with open('users.json', 'w') as users_json:
            users_json.write(json.dumps(users, indent=2))

        await ctx.send(f"<@{user_id}> (RYM username: **{rym_user}**) has been successfully removed from the bot.")

    @bot.command()
    async def setlastfm(ctx, *, arg):
        global users
        users[str(ctx.author.id)]["lfm"] = arg
        with open('users.json', 'w') as users_json:
            users_json.write(json.dumps(users, indent=2))
        await ctx.reply(f"Your last.fm account (**{arg}**) has been added.")

    @bot.command()
    async def importratings(ctx, *, arg=None):
        global cache
        if not cache.get("users"):
            cache["users"] = dict()
        if str(ctx.author.id) not in cache["users"]:
            cache["users"][str(ctx.author.id)] = rympy.SimpleUser(username=users[str(ctx.author.id)]["rym"])
        if arg:
            cache["users"][str(ctx.author.id)].import_ratings(url=arg)
        else:
            cache["users"][str(ctx.author.id)].import_ratings(url=ctx.message.attachments[0].url)
        
        await ctx.reply("Your ratings have been imported successfully.")

    @bot.command()
    async def w(ctx, *, arg=None):
        global users
        if not arg:
            user = lfm_network.get_user(users[str(ctx.author.id)]["lfm"])
            if not (current_track := user.get_now_playing()):
                last_track = user.get_recent_tracks(limit=1)[0]
                arg = str(last_track.track.artist) + " " + last_track.album.title()
            else:
                arg = str(current_track.artist) + " " + current_track.get_album().title
        try:
            release_info = get_release_info_from_google(arg)
        except KeyError:
            await ctx.send(f"The album **\"{arg}\"** was not found.")
            return
        cached_release = None
        if release_info['url'] in cache['releases']:
            cached_release = cache['releases'][release_info['url']]
        user_ratings = str()
        if release_info.get('year_position'):
            user_ratings += f"**#{release_info['year_position']}** for [{release_info['year']}](https://rateyourmusic.com/charts/top/{release_info['release_type'].lower()}/{release_info['year']}/{math.ceil(int(release_info['year_position'])/40)}/#pos{release_info['year_position']})"
            if release_info.get('overall_position'):
                user_ratings += f", **#{release_info['overall_position']}** [overall](https://rateyourmusic.com/charts/top/{release_info['release_type'].lower()}/all-time/deweight:live,archival,soundtrack/{math.ceil(int(release_info['overall_position'])/40)}/#pos{release_info['overall_position']})"
            user_ratings += "\n"
        
        if release_info.get('number_of_ratings'):
            user_ratings += f"**{release_info.get('average_rating')}** / 5.0 from {release_info.get('number_of_ratings')} ratings\n"
        
        if release_info.get('primary_genres'):
            user_ratings += f"**Primary genres:** {release_info['primary_genres']}\n"
            if cached_release:
                user_ratings += f"**Secondary genres:** {', '.join([genre.name for genre in cached_release.secondary_genres])}\n"
            user_ratings += "\n"

        one_month_ago = datetime.now() - timedelta(days=30)
        line_colour = 0x2d5ea9
        if cached_release:
            if cached_release.release_date and cached_release.release_date > one_month_ago:
                line_colour = 0x00df0d
            if cached_release.is_bolded:
                line_colour = 0x339a6d
            if "LGBT" in cached_release.descriptors:
                line_colour = 0xdc36b5
            if cached_release.average_rating <= 2.5:
                line_colour = 0xe4101a
            if cached_release.overall_position and cached_release.overall_position <= 250:
                line_colour = 0xf9b505
            if cached_release.is_nazi:
                line_colour = 0x2b2d31
        else:
            if release_info.get("release_date") and release_info["release_date"] > one_month_ago:
                line_colour = 0x00df0d
            if release_info.get("overall_position") and release_info["overall_position"] <= 7500:
                line_colour = 0x339a6d
            if release_info.get("average_rating") <= 2.5:
                line_colour = 0xe4101a
            if release_info.get("overall_position") and release_info["overall_position"] <= 250:
                line_colour = 0xf9b505

        
        if not cache.get("users"):
            cache["users"] = dict()

        average = (0,0)
        for user in cache["users"]:
            if cache["users"][user].ratings:
                for rating in cache["users"][user].ratings:
                    if rating.url == release_info['url'] or (rating.artist_name == release_info['artist_name'] and rating.title == release_info['title'] and rating.release_year == int(release_info["year"])) and rating.rating:
                        user_nick = ctx.guild.get_member(int(user)).display_name 
                        if ctx.author.id == int(user):
                            user_nick = "**" + user_nick + "**"
                        average = (average[0] + rating.rating, average[1] + 1)
                        star_rating = "<:star:1135605958333186149>" * int(rating.rating) + "<:half:1135605972564455434> "  * (1 if rating.rating != int(rating.rating) else 0)
                        user_ratings += f"◦ [{user_nick}]({rympy.ROOT_URL}/~{users[user]['rym']}) - {star_rating}\n"
                        break
        
        average_str = str()
        if average[1]:
            average = average[0]/average[1]
            average_str = f"\n\n**Sotão average rating:** {round(average, 2)} / 5.0"
        

        ratings_embed = discord.Embed(title=f"{release_info['artist_name']} - {release_info['title']} ({release_info['year']}, {release_info['release_type']})", description=user_ratings + average_str, color=line_colour, url=release_info['url'])
        if release_info.get('cover_url'):
            if cached_release:
                cover_url = cached_release.cover_url
            else:
                cover_url = release_info['cover_url']
            ratings_embed.set_thumbnail(url=cover_url)

        await ctx.send(embed=ratings_embed)

    @bot.command()
    async def c(ctx, *, arg=None):
        global rate_limit, cache
        if rate_limit:
            await ctx.reply("Rate limited. I'll send the collage as soon as possible.")
            while rate_limit:
                await asyncio.sleep(60)
                print(get_current_time_text(), f"Still waiting for {users[str(ctx.author.id)]['rym']}'s chart.")
        
        if arg not in ["3x3","4x4","5x5"]:
            arg = "3x3"

        size = int(arg[0])
        try:
            ratings = parse_ratings(users[str(ctx.author.id)]["rym"])
        except TypeError:
            await ctx.reply("Rate limited. I'll send the collage as soon as possible.")
            rate_limit = True
            await asyncio.sleep(60*15)
            rate_limit = False
            ratings = parse_ratings(users[str(ctx.author.id)]["rym"])
        
        album_titles_links = [(re.search(r" (.+) by",rating[0]).group(1),rating[1]) for rating in ratings]

        unfindable_albums = list()
        album_cover_links = list()
        for rym_title,link in album_titles_links:
            if link in cache["releases"] and cache["releases"][link].cover_url:
                album_cover_links.append((cache["releases"][link].cover_url, cache["releases"][link].title + "\n" + cache["releases"][link].artist_name))
                continue
            title_split = link.split("/")[-3:-1]
            title = " ".join(title_split).replace("-"," ")
            results = lfm_network.search_for_album(title).get_next_page()
            if results:
                album = lfm_network.search_for_album(title).get_next_page()[0]
                if album.get_cover_image():
                    album_cover_links.append((album.get_cover_image(), album.title + "\n" + str(album.artist)))
                else:
                    cover_url = google_search(title, search_type="image")[0]["link"]
                    if cover_url.endswith(".jpg"):
                        album_cover_links.append((cover_url, album.title + "\n" + str(album.artist)))
                    else:
                        unfindable_albums.append(title_split[0] + " - " + title_split[1])
            else:
                cover_url = google_search(title, search_type="image")[0]["link"]
                if cover_url.endswith(".jpg"):
                    album_cover_links.append((cover_url, album.title + "\n" + str(album.artist)))
                else:
                    unfindable_albums.append(title_split[0] + " - " + rym_title)
            
        album_covers = list()
        for link, text in album_cover_links:
            response = requests.get(link)
            img = Image.open(io.BytesIO(response.content))
            draw = ImageDraw.Draw(img)
            text_color = (255, 255, 255)
            shadow_color = (0, 0, 0)
            text_position = (3, 3)
            font = ImageFont.truetype('font.ttf', size=16)
            shadow_offset = 2
            shadow_position = (text_position[0] + shadow_offset, text_position[1] + shadow_offset)
            draw.text(shadow_position, text, font=font, fill=shadow_color)
            draw.text(text_position, text, font=font, fill=text_color)
            album_covers.append(img)

        collage_size = (size * 300, size * 300)

        collage = Image.new('RGB', collage_size)

        for i in range(size):
            for j in range(size):
                index = i * 3 + j
                if index < len(album_covers):
                    collage.paste(album_covers[index], (j * 300, i * 300))

        description = f"**User: [{ctx.author.display_name}](https://rateyourmusic.com/~{users[str(ctx.author.id)]['rym']})" 
        if unfindable_albums:
            description = "I couldn't find the following albums:\n- " + "\n- ".join(unfindable_albums)

        buffered_io = io.BytesIO()
        collage.save(buffered_io, format='JPEG')

        buffered_io.seek(0)

        await ctx.send(file=discord.File(fp=buffered_io, filename=f"{arg}_collage.jpeg"),
            embed=discord.Embed(title=f"Recent RYM ratings {arg} chart", description=description, color=0x2d5ea9))

    def gen_button(index, formatted_pages, embed, message, view, left):
        button = discord.ui.Button(label="◄")
        async def left_button_callback(interaction):
            nonlocal index, formatted_pages, embed, message, view
            if left:
                if index > 0:
                    index -= 1
            else:
                if index < len(formatted_pages) - 1:
                    index += 1
            embed.description = f"{formatted_pages[index]}\n\n**Page {index+1}/{len(formatted_pages)}**"
            await message.edit(embed=embed, view= view)
            await interaction.response.defer()
        button.callback = left_button_callback
        return button

    def gen_buttons(index, formatted_pages, embed, message, view):
        return gen_button(index, formatted_pages, embed, message, view, True), gen_button(index, formatted_pages, embed, message, view, False)

    @bot.command()
    async def genre(ctx, *, arg):
        global cache
        fixed_genre_name = str().join(char for char in arg.replace(" ","-").lower() if char == "-" or char.isalpha())
        cached_flag = False
        try:
            if cache.get("genres") and fixed_genre_name in cache.get("genres"):
                genre_obj = cache["genres"][fixed_genre_name]
                cached_flag = True
            else:
                genre_obj = rympy.Genre(name=arg)
                if not cache.get("genres"):
                    cache["genres"] = dict()
                cache["genres"][fixed_genre_name] = genre_obj

            genre_embed = discord.Embed(title=genre_obj.name, description=genre_obj.short_description, color=0x2d5ea9)
            
            if cached_flag:
                genre_message = await ctx.send(embed=genre_embed)
            else:
                genre_message = await ctx.reply(embed=genre_embed)

            genre_init_view = discord.ui.View(timeout= 300)

            init_button = discord.ui.Button(label="← Back")
            async def compact_button_callback(interaction):
                nonlocal genre_message, genre_init_view, genre_embed
                await genre_message.edit(embed=genre_embed, view= genre_init_view)
                await interaction.response.defer()
            init_button.callback = compact_button_callback

            #expand
            expanded_view = discord.ui.View(timeout= 300)
            expand_index = 0
            description_by_paragraphs = genre_obj.description.split("\n\n")
            word_counter = 0
            description_pages = list()
            temp_text = str()

            for paragraph in description_by_paragraphs:
                word_counter += len(paragraph.split())
                if word_counter > 200:
                    description_pages.append(temp_text)
                    temp_text = paragraph
                    word_counter = len(paragraph.split())
                else:
                    temp_text += "\n\n" + paragraph
            description_pages.append(temp_text)

            expanded_embed = discord.Embed(title=genre_obj.name, description=f"{description_pages[0]}\n\n**Page 1/{len(description_pages)}**", color=0x2d5ea9)

            expand_button = discord.ui.Button(label="Expand")
            async def expand_button_callback(interaction):
                nonlocal genre_message, expanded_embed, expanded_view
                await genre_message.edit(embed=expanded_embed, view= expanded_view)
                await interaction.response.defer()
            expand_button.callback = expand_button_callback

            #top 10
            top_view = discord.ui.View(timeout= 300)
            top_view.add_item(init_button)
            top_albums_button = discord.ui.Button(label="Top 10 Albums")
            top_albums_str = str()
            n = "\n"
            if len(genre_obj.top_ten_albums):
                for i, album in enumerate(genre_obj.top_ten_albums):
                    top_albums_str += f"{i+1}. [{album.artist_name.replace(n,'').strip()} - {album.title.replace(n,'').strip()}](https://rateyourmusic.com{album.url})\n"
            else:
                force_load_button = discord.ui.Button(label="Load list")
                async def force_load_button_callback(interaction):
                    nonlocal genre_message, top_embed, top_view
                    top_embed.description = "Fetching top albums from RYM..."
                    await genre_message.edit(embed=top_embed, view=top_view)
                    chart = genre_obj.top_chart
                    top_ten = chart.entries[:10]
                    top_albums_str = str()
                    for i, album in enumerate(top_ten):
                        top_albums_str += f"{i+1}. [{album.artist_name.replace(n,'').strip()} - {album.title.replace(n,'').strip()}](https://rateyourmusic.com{album.url})\n"
                    top_embed.description = top_albums_str
                    await genre_message.edit(embed=top_embed, view=top_view)
                    top_view.remove_item(force_load_button)
                    await interaction.response.defer()

                force_load_button.callback = force_load_button_callback
                top_view.add_item(force_load_button)


            top_embed = discord.Embed(title=f"Top 10 {genre_obj.name} albums", description=top_albums_str, color=0x2d5ea9)
            async def top_albums_button_callback(interaction):
                nonlocal genre_message, top_embed, top_view
                await genre_message.edit(embed=top_embed, view= top_view)
                await interaction.response.defer()
            top_albums_button.callback = top_albums_button_callback
            
            bold_ascii_alphabet = {
                'A': '𝗔', 'B': '𝗕', 'C': '𝗖', 'D': '𝗗', 'E': '𝗘',
                'F': '𝗙', 'G': '𝗚', 'H': '𝗛', 'I': '𝗜', 'J': '𝗝',
                'K': '𝗞', 'L': '𝗟', 'M': '𝗠', 'N': '𝗡', 'O': '𝗢',
                'P': '𝗣', 'Q': '𝗤', 'R': '𝗥', 'S': '𝗦', 'T': '𝗧',
                'U': '𝗨', 'V': '𝗩', 'W': '𝗪', 'X': '𝗫', 'Y': '𝗬',
                'Z': '𝗭', " ": " "
            }
            
            hierarchy_genre_buttons = list()
            parent_genres_view = None
            if genre_obj.parent_genres:
                #parent genres
                parent_genres_view = discord.ui.View(timeout= 300)
                parent_genres_button = discord.ui.Button(label="Parent genres")
                parent_genre_formatted_description = str().join(parent_genre.name + "\n|\n" for parent_genre in genre_obj.parent_genres) + f"└-- {str().join(bold_ascii_alphabet[letter.upper()] for letter in genre_obj.name)}"
                parent_genres_embed = discord.Embed(title=f"{genre_obj.name} parent genre hierarchy", description=f"```\n{parent_genre_formatted_description}```")
                async def parent_genres_button_callback(interaction):
                    nonlocal genre_message, parent_genres_embed, parent_genres_view
                    await genre_message.edit(embed=parent_genres_embed, view= parent_genres_view)
                    await interaction.response.defer()
                parent_genres_button.callback = parent_genres_button_callback
                hierarchy_genre_buttons.append(parent_genres_button)
                
            #children genres
            children_genres_view = None
            if genre_obj.children_genres:
                children_genres_view = discord.ui.View(timeout= 300)
                children_genres_button = discord.ui.Button(label="Children genres")
                children_genre_formatted_description = f"**{genre_obj.name}**"
                def recursive_children_search(space_count, children_genres):
                    description_fragment = str()
                    if children_genres:
                        for child in children_genres:
                            description_fragment +=  " "*space_count + "\n" + " "*space_count + "|\n" + " "*space_count + f"└-- {child.name}"
                            fixed_name = str().join(char for char in child.name.replace(" ","-").lower() if char == "-" or char.isalpha())
                            if fixed_name in cache["genres"]:
                                description_fragment += recursive_children_search(space_count+4,cache["genres"][fixed_name].children_genres)
                    return description_fragment
                children_genre_formatted_description = str().join(bold_ascii_alphabet[letter.upper()] for letter in genre_obj.name)
                children_genre_formatted_description += recursive_children_search(0, genre_obj.children_genres)
                children_genre_formatted_split = children_genre_formatted_description.split("\n")
                children_genre_formatted_pages = ["```\n" + "\n".join(children_genre_formatted_split[i:i+14]) + "```" for i in range(0,len(children_genre_formatted_split),14)]

                children_genres_embed = discord.Embed(title=f"{genre_obj.name} children genre hierarchy", description=f"{children_genre_formatted_pages[0]}\nPage 1/{len(children_genre_formatted_pages)}")
                async def children_genres_button_callback(interaction):
                    nonlocal genre_message, children_genres_embed, children_genres_view
                    await genre_message.edit(embed=children_genres_embed, view= children_genres_view)
                    await interaction.response.defer()
                children_genres_button.callback = children_genres_button_callback
                hierarchy_genre_buttons.append(children_genres_button)
                hierarchy_index = 0
                left_button_child, right_button_child = gen_buttons(hierarchy_index, children_genre_formatted_pages, children_genres_embed, genre_message, children_genres_view)
                
            left_button, right_button = gen_buttons(expand_index, description_pages, expanded_embed, genre_message, expanded_view)

            genre_init_view.add_item(expand_button)
            genre_init_view.add_item(top_albums_button)
            for button in hierarchy_genre_buttons:
                genre_init_view.add_item(button)
            if parent_genres_view:
                parent_genres_view.add_item(init_button)
            if children_genres_view:
                children_genres_view.add_item(init_button)
                children_genres_view.add_item(left_button_child)
                children_genres_view.add_item(right_button_child)
            expanded_view.add_item(init_button)
            expanded_view.add_item(left_button)
            expanded_view.add_item(right_button)

            await genre_message.edit(embed=genre_embed, view= genre_init_view)
        except rympy.RequestFailed:
            await ctx.send("The requested genre doesn't exist.")

    @bot.command()
    async def userlist(ctx):
        user_list_pages = list()
        user_counter = 1
        user_list_init = list()
        for user in users:
            user_list_init.append((ctx.guild.get_member(int(user)),f"<@{user}>: [{users[user]['rym']}]({'https://rateyourmusic.com/~' + users[user]['rym']})"))
            user_counter += 1

        user_list_init.sort(key=lambda x: x[0].display_name)
        user_list_pages = ["\n".join([text for _, text in user_list_init[i:i + 10]]) for i in range(0, len(user_list_init), 10)]

        page_index = 0

        user_list_embed = discord.Embed(title="Users saved in the bot", description=f"{user_list_pages[0]}\n\n**Page 1/{len(user_list_pages)}**", color=0x2d5ea9)
        userlist_message = await ctx.send(embed=user_list_embed)
        
        user_list_view = discord.ui.View(timeout= 300)

        left_button, right_button = gen_buttons(page_index, user_list_pages, user_list_embed, userlist_message, user_list_view)

        user_list_view.add_item(left_button)
        user_list_view.add_item(right_button)

        await userlist_message.edit(embed=user_list_embed, view= user_list_view)

    
    @bot.command()
    async def forceupdate(ctx):
        if vars.admin_role_name not in [role.name for role in ctx.author.roles] and ctx.author.id not in vars.whitelisted_ids:
            return
        
        global users

        feed_channel = bot.get_channel(vars.channel_id)
        for user_id in users:
            member = ctx.guild.get_member(int(user_id))

            users[user_id]["last"] = await get_recent_info(member, users[user_id]["rym"], users[user_id]["last"], feed_channel)

            with open('users.json', 'w') as users_json:
                users_json.write(json.dumps(users, indent=2))

    @bot.command()
    async def forcesave(ctx):
        global users, last, active_id
        last = users[active_id]["last"]
        if vars.admin_role_name not in [role.name for role in ctx.author.roles] and ctx.author.id not in vars.whitelisted_ids:
            return
        
        with open('users.json', 'w') as users_json:
            users_json.write(json.dumps(users, indent=2))
        
        with lzma.open('cache_tmp.lzma', 'wb') as file:
            pickle.dump(cache, file)

        shutil.copy2("cache_tmp.lzma", "cache.lzma")
        
        await ctx.reply("Info saved successfully.")

    @bot.command()
    async def loadcache(ctx):
        global users, cache
        if vars.admin_role_name not in [role.name for role in ctx.author.roles] and ctx.author.id not in vars.whitelisted_ids:
            return
        
        with lzma.open('cache.lzma', 'rb') as file:
            cache = pickle.load(file)
            if cache.get("simple_releases"):
                for release in cache.get("simple_releases"):
                    if release in cache.get("releases"):
                        cache["simple_releases"].pop(release)
        
        await ctx.reply("Cache loaded successfully.")

    @bot.command()
    async def savecache(ctx):
        global users, cache
        if vars.admin_role_name not in [role.name for role in ctx.author.roles] and ctx.author.id not in vars.whitelisted_ids:
            return
        
        with lzma.open('cache_tmp.lzma', 'wb') as file:
            pickle.dump(cache, file)
        
        await ctx.reply("Info saved successfully.")

    @bot.command()
    async def save(ctx):
        global users, cache
        if vars.admin_role_name not in [role.name for role in ctx.author.roles] and ctx.author.id not in vars.whitelisted_ids:
            return
        
        with open('users.json', 'w') as users_json:
            users_json.write(json.dumps(users, indent=2))

        with lzma.open('cache.lzma', 'wb') as file:
            pickle.dump(cache, file)
        
        await ctx.reply("Info saved successfully.")

    @bot.command()
    async def user(ctx, *, arg=None):
        global users
        end_str = str()

        if not(arg):
            rym = users[str(ctx.author.id)]["rym"]
            if lfm := users[str(ctx.author.id)].get("lfm"):
                end_str = f"\naLast.fm profile: https://www.last.fm/user/{lfm}"
            await ctx.send(f"Your RYM profile:\nhttps://rateyourmusic.com/~{rym}")
            return
        
        user_id = re.search(r"<@(\d{18)}>|(\d{18})", arg).group()
        
        try:
            rym = users[user_id]["rym"]
        except KeyError:
            await ctx.send("That user is not connected to the bot.")
            return
        
        member = ctx.guild.get_member(int(user_id))

        if lfm := users[user_id].get("lfm"):
            end_str = f"\naLast.fm profile: https://www.last.fm/user/{lfm}"
        await ctx.send(f"**{member.display_name}**'s RYM profile: https://rateyourmusic.com/~{rym}{end_str}")
        
    bot.run(vars.token)

if __name__ == "__main__":
    main()