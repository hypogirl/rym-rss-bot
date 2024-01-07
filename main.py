import asyncio
import random
import json
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

global users, last, active_id, remove_users_message
remove_users_message = dict()
last = None
active_id = None
users = dict()

with open('users.json') as users_json:
    users = json.load(users_json)

def get_current_time_text():
    now = datetime.now()
    current_time = now.strftime("%H:%M:%S")
    return "[" + current_time + "]"

def get_review(description_elem):
    if review_elem := description_elem.find('span'):
        return ET.tostring(review_elem)[28:-7].decode('utf-8').replace("<br />", "\n").replace("<b>", "**").replace("</b>", "**")
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

async def get_recent_info(user_id, member, rym_user, last_tmp, feed_channel):
    global remove_users_message
    ratings = parse_ratings(rym_user)
    try:
        print(get_current_time_text(), member.display_name, "parsed.\n")
    except:
        remove_message = await feed_channel.send(f"<@{user_id}> já nao está no server.")
        remove_users_message[remove_message.id] = user_id
        return

    rating_info_list = list()

    for (text, rym_url, review, timestamp) in ratings:
        if timestamp == last:
            break

        if rym_url.startswith("https://rateyourmusic.com/film/"):
            continue

        text_info = re.findall(r"(Rated) .* (\d\.\d) star|(Reviewed)", text)   # text_info will be a list with a structure similar to the following two:
                                                                                # ["Rated", "2.5", ""] in case it's a rating
                                                                                # ["", "", "Reviewed"] in case it's a review

        await asyncio.sleep(120)
        print(get_current_time_text(), rym_url)
        
        release = rympy.Release(url=rym_url)

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

        if release.secondary_genres:
            secondary_genres = "*" + release.secondary_genres + "*"
        else:
            secondary_genres = str()
        body_text = f"{release.primary_genres or ''}\n{secondary_genres}\n\n**{date}** {star_rating}\n{review}"
        avatar_url = member.avatar.url if member.avatar else "https://e.snmc.io/3.0/img/logo/sonemic-32.png"
        user_url = f"https://rateyourmusic.com/~{rym_user}"

        rated_text += (' an ' if release.type in ['Album', 'EP'] else ' a ') + release.type
        if release.release_date.year:
            release_year = "(" + release.release_date.year + ")"
        else:
            release_year = str()

        rating_info = {
            "title": f"{release.artist_name} - {release.title}{release_year}",
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
        global users
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
                    last = await get_recent_info(user_id, member, users[user_id]["rym"], users[user_id]["last"], feed_channel)
                except:
                    with open("error.log", "a") as error_file:
                        error_file.write(traceback.format_exc() + "\n\n")
                    await feed_channel.send(f"Error found while getting rating data. Check log file. <@{vars.whitelisted_ids[-1]}>")
                else:
                    users[user_id]["last"] = last

                await asyncio.sleep(60)

            with open('users_temp.json', 'w') as users_json:
                users_json.write(json.dumps(users, indent=2))
                    

            print(get_current_time_text(), f"sleeping for {vars.sleep_minutes} minutes")

            await asyncio.sleep(vars.sleep_minutes * 60)

    async def gen_add(rym_user, user_id, sendable):
        global users

        ratings = parse_ratings(rym_user)
        last = ratings[0][3]

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

        discord_rym_user = re.findall(r"(<@(\d{18})>|\d{18}) +(\w+)", arg)
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
            if page_index < len(user_list_pages):
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
    async def save(ctx):
        global users
        if vars.admin_role_name not in [role.name for role in ctx.author.roles] and ctx.author.id not in vars.whitelisted_ids:
            return
        
        with open('users.json', 'w') as users_json:
            users_json.write(json.dumps(users, indent=2))
        
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