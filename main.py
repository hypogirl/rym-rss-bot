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
from simple_rym_api import *

global users
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
    global users
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

async def get_recent_info(member, rym_user, last, feed_channel):
    ratings = parse_ratings(rym_user)
    print(get_current_time_text(), member.display_name, "parsed.\n")

    rating_info_list = list()

    for (text, rym_url, review, timestamp) in ratings:
        if timestamp == last:
            break

        text_info = re.findall(r"(Rated) .* (\d\.\d) star|(Reviewed)", text)   # text_info will be a list with a structure similar to the following two:
                                                                                # ["Rated", "2.5", ""] in case it's a rating
                                                                                # ["", "", "Reviewed"] in case it's a review

        await asyncio.sleep(60)
        print(get_current_time_text(), rym_url)

        if rym_url.startswith("https://rateyourmusic.com/film/"):
            continue
        
        release_info = get_release_info(rym_url)

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

        if release_info['secondary_genres']:
            secondary_genres = "*" + release_info["secondary_genres"] + "*"
        else:
            secondary_genres = str()
        body_text = f"{release_info['primary_genres'] or ''}\n{secondary_genres}\n\n**{date}** {star_rating}\n{review}"
        avatar_url = member.avatar.url if member.avatar else "https://e.snmc.io/3.0/img/logo/sonemic-32.png"
        user_url = f"https://rateyourmusic.com/~{rym_user}"

        rated_text += (' an ' if release_info['release_type'] in ['Album', 'EP'] else ' a ') + release_info['release_type']
        if release_info["release_year"]:
            release_year = "(" + release_info["release_year"] + ")"
        else:
            release_year = str()

        rating_info = {
            "title": f"{release_info['artist']} - {release_info['release_title']}{release_year}",
            "description": body_text,
            "url": rym_url,
            "author": f"{member.display_name} {rated_text}",
            "icon_url": avatar_url,
            "user_url": user_url,
            "thumbnail_url": release_info['release_cover_url'] if release_info['release_cover_url'] else None,
            "streaming_links": release_info['release_links']
        }

        rating_info_list.append(rating_info)

        if not(last):
            break
    
    return {
        "last": ratings[0][3],
        "ratings": rating_info_list
        }

def main():
    intents = discord.Intents.all()
    bot = commands.Bot(command_prefix= vars.command_prefix, intents= intents)
    tree = discord.app_commands.CommandTree(bot)

    @bot.event
    async def on_ready():
        global users
        print(f'Logged in as {bot.user}.\n')
        
        feed_channel = bot.get_channel(vars.channel_id)
        
        while True:
            print(get_current_time_text(), "fetching updates...")
            users_rating_data = list()
            rating_counter = 0
            for user_id in list(users):
                member = bot.get_guild(vars.guild_id).get_member(int(user_id))

                try:
                    rating_data = await get_recent_info(member, users[user_id]["rym"], users[user_id]["last"], feed_channel)
                except:
                    with open("error.log", "a") as error_file:
                        error_file.write(traceback.format_exc() + "\n\n")
                    await feed_channel.send(f"Error found while getting rating data. Check log file. <@{vars.whitelisted_ids[-1]}>")
                else:
                    users[user_id]["last"] = rating_data["last"]
                    users_rating_data.append(rating_data["ratings"])
                    rating_counter += len(rating_data["ratings"])

                await asyncio.sleep(60)

            with open('users_temp.json', 'w') as users_json:
                users_json.write(json.dumps(users, indent=2))

            random.shuffle(users_rating_data)
            for rating_info_list in users_rating_data:
                for rating_info in rating_info_list[::-1]:
                    print(f"{rating_info['title'][:255]}\n{rating_info['description']}")
                    rating_embed = discord.Embed(title=rating_info['title'][:255], description=rating_info['description'], color=0x2d5ea9, url=rating_info['url'])
                    rating_embed.set_author(name=rating_info['author'], icon_url=rating_info['icon_url'], url=rating_info['user_url'])
                    if rating_info['thumbnail_url']:
                        rating_embed.set_thumbnail(url=rating_info['thumbnail_url'])

                    links_view = discord.ui.View(timeout= None)

                    button_list = [None] * 5
                    for platform in rating_info["streaming_links"]:
                        match platform:
                            case "spotify":
                                id = next(iter(rating_info["streaming_links"]["spotify"]))
                                release_link = f"https://open.spotify.com/album/{id}"
                                platform_emoji = discord.PartialEmoji.from_str("<:sp:1141025089878499389>")
                                index = 0
                            case "youtube":
                                id = next(iter(rating_info["streaming_links"]["youtube"]))
                                release_link = f"https://www.youtube.com/watch?v={id}"
                                platform_emoji = discord.PartialEmoji.from_str("<:yc:1140967863931392040>")
                                index = 1
                            case "bandcamp":
                                bandcamp_dict = rating_info["streaming_links"]["bandcamp"]
                                url = [value["url"] for value in bandcamp_dict.values() if value["url"]][0]
                                release_link = "https://" + url
                                platform_emoji = discord.PartialEmoji.from_str("<:bc:1140967203596927017>")
                                index = 2
                            case "soundcloud":
                                soundcloud_dict = rating_info["streaming_links"]["soundcloud"]
                                url = [value["url"] for value in soundcloud_dict.values() if value["url"]][0]
                                release_link = "https://" + url
                                platform_emoji= discord.PartialEmoji.from_str("<:sc:1140968078746857492>")
                                index = 3
                            case "applemusic":
                                id = next(iter(rating_info["streaming_links"]["applemusic"]))
                                applemusic_values = rating_info["streaming_links"]["applemusic"].values()
                                (loc, album) = [(value["loc"], value["album"]) for value in applemusic_values][0]
                                release_link = f"https://music.apple.com/{loc}/album/{album}/{id}"
                                platform_emoji = discord.PartialEmoji.from_str("<:ac:1140967868708696104>")
                                index = 4
                    
                        if release_link:
                            button = discord.ui.Button(url= release_link, emoji= platform_emoji)
                            button_list[index] = button
                    
                    button_count = 0
                    for button in button_list:
                        if button_count == 3:
                            break
                        if button:
                            links_view.add_item(button)
                            button_count += 1

                    await feed_channel.send(embed=rating_embed, view= links_view)
                    await asyncio.sleep(120)

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