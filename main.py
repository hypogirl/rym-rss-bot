import asyncio
import random
import json
import pickle
import lzma
import re
import traceback
from datetime import datetime
import discord
from discord.ext import commands
import xml.etree.ElementTree as ET
import vars
import requests
import rympy
from bs4 import BeautifulSoup

global users, last, active_id, last_url
last = None
active_id = None
users = dict()
cache = dict()
date_format = "%a, %d %b %Y %H:%M:%S %z"

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

def get_review(description_elem):
    if review_elem := description_elem.find('span'):
        return review_elem.text.strip()
    else:
        return None

def parse_ratings(rym_user):
    url = f"https://rateyourmusic.com/~{rym_user}/data/rss"
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'}
    rss_response = requests.get(url, headers=headers) # get request using a browser header to avoid a RYM ban
    print(rss_response.content)
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

async def get_recent_info(member, rym_user, last_tmp, feed_channel):
    ratings = parse_ratings(rym_user)
    print(get_current_time_text(), member.display_name, "parsed.\n")

    global users, last, active_id, last_url, cache

    last = last_tmp
    active_id = str(member.id)

    i = 0
    users[active_id]["last"] = ratings[0][3]
    for (text, rym_url, review, timestamp) in ratings:
        if datetime.strptime(timestamp, date_format) <= datetime.strptime(last, date_format):
            break

        i += 1

        if rym_url.startswith("https://rateyourmusic.com/film/"):
            continue

        text_info = re.findall(r"(Rated) .* (\d\.\d) star|(Reviewed)", text)   # text_info will be a list with a structure similar to the following two:
                                                                                # ["Rated", "2.5", ""] in case it's a rating
                                                                                # ["", "", "Reviewed"] in case it's a review

        await asyncio.sleep(120)
        if datetime.strptime(timestamp, date_format) <= datetime.strptime(last, date_format):
            break
        print(get_current_time_text(), rym_url)
        
        last_url = rym_url
        if cache.get("releases") and rym_url in cache["releases"]:
            release = cache["releases"][rym_url]
        else:
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

        if rating:
            star_rating = "<:star:1135605958333186149>" * int(rating) + "<:half:1135605972564455434> "  * (1 if rating != int(rating) else 0) # this simply makes a string with star (and half star) emojis corresponding to the user's rating
        else:
            star_rating = str()

        date = re.search(r"\d{1,2} \w{3}", timestamp).group() # getting the day and month

        if release.primary_genres:
            primary_genres = ", ".join([genre.name for genre in release.primary_genres])

        if release.secondary_genres:
            secondary_genres = "*" + ", ".join([genre.name for genre in release.secondary_genres]) + "*"
        else:
            secondary_genres = str()
        body_text = f"{primary_genres}\n{secondary_genres}\n\n**{date}** {star_rating}\n{review}"
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

        rating_embed = discord.Embed(title=rating_info['title'][:255], description=rating_info['description'], color=0x2d5ea9, url=rating_info['url'])
        rating_embed.set_author(name=rating_info['author'], icon_url=rating_info['icon_url'], url=rating_info['user_url'])

        if rating_info['thumbnail_url']:
            rating_embed.set_thumbnail(url=rating_info['thumbnail_url'])

        links_view = discord.ui.View(timeout= None)
        button_list = list()

        if release.links.spotify:
            button_list.append(discord.ui.Button(url= release.links.spotify, emoji= discord.PartialEmoji.from_str("<:sp:1141025089878499389>")))

        if release.links.youtube:
            button_list.append(discord.ui.Button(url= release.links.youtube, emoji= discord.PartialEmoji.from_str("<:yc:1140967863931392040>")))
        
        if release.links.bandcamp:
            button_list.append(discord.ui.Button(url= release.links.bandcamp, emoji= discord.PartialEmoji.from_str("<:bc:1140967203596927017>")))
        
        if release.links.soundcloud:
            button_list.append(discord.ui.Button(url= release.links.soundcloud, emoji= discord.PartialEmoji.from_str("<:sc:1140968078746857492>")))
        
        if release.links.apple_music:
            button_list.append(discord.ui.Button(url= release.links.apple_music, emoji= discord.PartialEmoji.from_str("<:ac:1140967868708696104>")))

        button_count = 0
        for button in button_list:
            if button_count == 3:
                break
            if button:
                links_view.add_item(button)
                button_count += 1
        await feed_channel.send(embed=rating_embed, view= links_view)

        if not(last):
            break
    
    return ratings[0][3]

def main():
    intents = discord.Intents.all()
    bot = commands.Bot(command_prefix= vars.command_prefix, intents= intents)

    @bot.event
    async def on_ready():
        global users, last_url
        print(f'Logged in as {bot.user}.\n')
        
        feed_channel = bot.get_channel(vars.channel_id)
        
        while True:
            print(get_current_time_text(), "fetching updates...")
            print(users)
            users_list = list(users)
            random.shuffle(users_list)
            for user_id in users_list:
                member = bot.get_guild(vars.guild_id).get_member(int(user_id))

                try:
                    last = await get_recent_info(member, users[user_id]["rym"], users[user_id]["last"], feed_channel)
                except:
                    with open("error.log", "a") as error_file:
                        error_file.write(last_url + "\n" + traceback.format_exc() + "\n\n")
                    await feed_channel.send(f"Error found while getting rating data. Check log file. <@{vars.whitelisted_ids[-1]}>")
                else:
                    users[user_id]["last"] = last

                await asyncio.sleep(60)

            with open('users_temp.json', 'w') as users_json:
                users_json.write(json.dumps(users, indent=2))
                    

            print(get_current_time_text(), f"sleeping for {vars.sleep_minutes} minutes")
            
            global cache
            with lzma.open('cache.lzma', 'wb') as file:
                pickle.dump(cache, file)

            await asyncio.sleep(vars.sleep_minutes * 60)

    async def gen_add(rym_user, user_id, sendable):
        global users

        ratings = parse_ratings(rym_user)
        last = ratings[0][3] if ratings[0][3] else None

        users[user_id] = {
            "rym": rym_user,
            "last": last
            }
        
        with open('users_temp.json', 'w') as users_json:
            users_json.write(json.dumps(users, indent=2))

        await sendable.send(f"<@{user_id}> (RYM username: **{rym_user}**) has been successfully added to the bot.")

    @bot.command()
    async def add(ctx, *, arg):
        if vars.admin_role_name not in [role.name for role in ctx.author.roles] and ctx.author.id not in vars.whitelisted_ids:
            return

        discord_rym_user = re.findall(r"(<@(\d+)>|\d+) +(\w+)", arg)
        user_id = discord_rym_user[0][1]
        rym_user = discord_rym_user[0][2]
        await gen_add(rym_user, user_id, ctx)

    #@tree.command(name = "add")
    #async def slash_add(interaction, discord_user: str, rym_user: str):
    #    user_id = re.search(r"\d+", discord_user).group()

    @bot.command()
    async def remove(ctx, *, arg):
        if vars.admin_role_name not in [role.name for role in ctx.author.roles] and ctx.author.id not in vars.whitelisted_ids:
            return
        
        global users
        user_id = re.search(r"<@(\d{18)}>|(\d{18})", arg).group()
        rym_user = users[user_id]["rym"]
        if user_id not in users:
            await ctx.send(f"This user is not connected to the bot.")
            return
        users.pop(user_id)

        with open('users_temp.json', 'w') as users_json:
            users_json.write(json.dumps(users, indent=2))

        await ctx.send(f"<@{user_id}> (RYM username: **{rym_user}**) has been successfully removed from the bot.")

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
                    top_albums_str += f"**{i+1}.** [{album.artist_name.replace(n,'').strip()} - {album.title.replace(n,'').strip()}](https://rateyourmusic.com{album.url})\n"
            else:
                force_load_button = discord.ui.Button(label="Load list")
                async def force_load_button_callback(interaction):
                    nonlocal genre_message, top_embed, top_albums_str, top_view
                    top_embed.description = "Fetching top albums from RYM..."
                    await genre_message.edit(embed=top_embed, view=top_view)
                    chart = genre_obj.top_chart
                    top_ten = chart.entries[:10]
                    for i, album in enumerate(top_ten):
                        top_albums_str += f"**{i+1}.** [{album.artist_name.replace(n,'').strip()} - {album.title.replace(n,'').strip()}](https://rateyourmusic.com{album.url})\n"
                    
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
                ' ': ' ',
                'a': '𝐴',
                'b': '𝐵',
                'c': '𝐶',
                'd': '𝐷',
                'e': '𝐸',
                'f': '𝐹',
                'g': '𝐺',
                'h': '𝐻',
                'i': '𝐼',
                'j': '𝐽',
                'k': '𝐾',
                'l': '𝐿',
                'm': '𝑀',
                'n': '𝑁',
                'o': '𝑂',
                'p': '𝑃',
                'q': '𝑄',
                'r': '𝑅',
                's': '𝑆',
                't': '𝑇',
                'u': '𝑈',
                'v': '𝑉',
                'w': '𝑊',
                'x': '𝑋',
                'y': '𝑌',
                'z': '𝑍',
            }
            
            hierarchy_genre_buttons = list()
            parent_genres_view = None
            if genre_obj.parent_genres:
                #parent genres
                parent_genres_view = discord.ui.View(timeout= 300)
                parent_genres_button = discord.ui.Button(label="Parent genres")
                parent_genre_formatted_description = str().join(parent_genre.name + "\n|\n" for parent_genre in genre_obj.parent_genres) + f"└-- {str().join(bold_ascii_alphabet[letter.lower()] for letter in genre_obj.name)}"
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
                children_genre_formatted_description = str().join(bold_ascii_alphabet[letter.lower()] for letter in genre_obj.name)
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
                left_button_child = discord.ui.Button(label="◄")
                async def left_button_callback(interaction):
                    nonlocal hierarchy_index, children_genre_formatted_pages, children_genres_embed, genre_message, children_genres_view
                    if hierarchy_index > 0:
                        hierarchy_index -= 1
                    children_genres_embed.description = f"{children_genre_formatted_pages[hierarchy_index]}\n\n**Page {hierarchy_index+1}/{len(children_genre_formatted_pages)}**"
                    await genre_message.edit(embed=children_genres_embed, view= children_genres_view)
                    await interaction.response.defer()
                left_button_child.callback = left_button_callback

                right_button_child = discord.ui.Button(label="►")
                async def right_button_callback(interaction):
                    nonlocal hierarchy_index, children_genre_formatted_pages, children_genres_embed, genre_message, children_genres_view
                    if hierarchy_index < len(children_genre_formatted_pages) - 1:
                        hierarchy_index += 1
                    children_genres_embed.description = f"{children_genre_formatted_pages[hierarchy_index]}\n\n**Page {hierarchy_index+1}/{len(children_genre_formatted_pages)}**"
                    await genre_message.edit(embed=children_genres_embed, view= children_genres_view)
                    await interaction.response.defer()
                right_button_child.callback = right_button_callback

            left_button = discord.ui.Button(label="◄")
            async def left_button_callback(interaction):
                nonlocal expand_index, description_pages, expanded_embed, genre_message, expanded_view
                if expand_index > 0:
                    expand_index -= 1
                expanded_embed.description = f"{description_pages[expand_index]}\n\n**Page {expand_index+1}/{len(description_pages)}**"
                await genre_message.edit(embed=expanded_embed, view= expanded_view)
                await interaction.response.defer()
            left_button.callback = left_button_callback

            right_button = discord.ui.Button(label="►")
            async def right_button_callback(interaction):
                nonlocal expand_index, description_pages, expanded_embed, genre_message, expanded_view
                if expand_index < len(description_pages) - 1:
                    expand_index += 1
                expanded_embed.description = f"{description_pages[expand_index]}\n\n**Page {expand_index+1}/{len(description_pages)}**"
                await genre_message.edit(embed=expanded_embed, view= expanded_view)
                await interaction.response.defer()
            right_button.callback = right_button_callback

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

        left_button = discord.ui.Button(label="◄")
        async def left_button_callback(interaction):
            nonlocal page_index, user_list_embed, userlist_message
            if page_index > 0:
                page_index -= 1
            user_list_embed.description = f"{user_list_pages[page_index]}\n\n**Page {page_index+1}/{len(user_list_pages)}**"
            await userlist_message.edit(embed=user_list_embed, view= user_list_view)
            await interaction.response.defer()

        left_button.callback = left_button_callback

        right_button = discord.ui.Button(label="►")
        async def right_button_callback(interaction):
            nonlocal page_index, user_list_embed, userlist_message
            if page_index < len(user_list_pages) - 1:
                page_index += 1
            user_list_embed.description = f"{user_list_pages[page_index]}\n\n**Page {page_index+1}/{len(user_list_pages)}**"
            await userlist_message.edit(embed=user_list_embed, view= user_list_view)
            await interaction.response.defer()

        right_button.callback = right_button_callback

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

            with open('users_temp.json', 'w') as users_json:
                users_json.write(json.dumps(users, indent=2))

    @bot.command()
    async def forcesave(ctx):
        global users, last, active_id
        last = users[active_id]["last"]
        if vars.admin_role_name not in [role.name for role in ctx.author.roles] and ctx.author.id not in vars.whitelisted_ids:
            return
        
        with open('users.json', 'w') as users_json:
            users_json.write(json.dumps(users, indent=2))
        
        with lzma.open('cache.lzma', 'wb') as file:
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

        if not(arg):
            rym = users[str(ctx.author.id)]["rym"]
            await ctx.send(f"Your RYM profile:\nhttps://rateyourmusic.com/~{rym}")
            return
        
        user_id = re.search(r"<@(\d{18)}>|(\d{18})", arg).group()
        
        try:
            rym = users[user_id]["rym"]
        except KeyError:
            await ctx.send("That user is not connected to the bot.")
            return
        member = ctx.guild.get_member(int(user_id))
        await ctx.send(f"**{member.display_name}**'s RYM profile:\nhttps://rateyourmusic.com/~{rym}")
        
    bot.run(vars.token)

if __name__ == "__main__":
    main()