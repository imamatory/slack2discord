#!/usr/bin/env python3
# Author: Rocky Slavin
# Slack message history importer for Discord
import json
import os
import time
from datetime import datetime
from discord.ext import commands
import discord
import io
import aiohttp

THROTTLE_TIME_SECONDS = 0.1


def get_file_paths(file_path):
    """
    Returns a list of json files (either the path itself or nested files if the path is a directory).
    :param file_path: String path to directory or file
    :return: List of corresponding .json files
    """
    json_files = []

    # if directory, load files
    if os.path.isdir(file_path):
        json_files = [os.path.join(file_path, f) for f in os.listdir(
            file_path) if f.endswith('.json')]
    elif file_path.endswith('.json'):
        json_files.append(file_path)

    if not json_files:
        print(f'[ERROR] No .json files found at {file_path}')
    else:
        print(f'[INFO] {len(json_files)} .json files loaded')

    return json_files


def get_display_names(json_file_paths):
    """
    Generates a dictionary of user_id => display_name pairs
    :param json_file_paths: List of paths being parsed
    :return: Dictionary or None if no file is found
    """
    users = {}

    print(f'[INFO] Attempting to locate users.json')

    user_file_path_dir = os.path.join(
        os.path.dirname(json_file_paths[0]), 'users.json')
    user_file_path_files = os.path.join(os.path.dirname(
        os.path.dirname(json_file_paths[0])), 'users.json')

    if os.path.isfile(user_file_path_dir):
        file_path = user_file_path_dir
    elif os.path.isfile(user_file_path_files):
        file_path = user_file_path_files
    else:
        print(f'[ERROR] Unable to locate users.json')
        return None

    try:
        with open(file_path, encoding='utf-8') as f:
            users_json = json.load(f)
            for user in users_json:
                users[user['id']] = (
                    user['profile']['display_name'] if user['profile']['display_name'] else user['profile'][
                        'real_name'])
                print(
                    f"\tUser ID: {user['id']} -> Display Name: {users[user['id']]}")
    except Exception as e:
        print(f'[ERROR] Unable to load display names: {e}')
        return None
    return users


def get_channel_names(json_file_paths):
    """
    Generates a dictionary of channel_id => channel_name pairs
    :param json_file_paths: List of paths being parsed
    :return: Dictionary or None if no file is found
    """
    channels = {}

    print(f'[INFO] Attempting to locate channels.json')

    channel_file_path_dir = os.path.join(
        os.path.dirname(json_file_paths[0]), 'channels.json')
    channel_file_path_files = os.path.join(os.path.dirname(
        os.path.dirname(json_file_paths[0])), 'channels.json')

    if os.path.isfile(channel_file_path_dir):
        file_path = channel_file_path_dir
    elif os.path.isfile(channel_file_path_files):
        file_path = channel_file_path_files
    else:
        print(f'[ERROR] Unable to locate channels.json')
        return None

    try:
        with open(file_path, encoding='utf-8') as f:
            channels_json = json.load(f)
            for channel in channels_json:
                channels[channel['id']] = channel['name']
                print(
                    f"\tChannel ID: {channel['id']} -> Channel Name: {channels[channel['id']]}")
    except Exception as e:
        print(f'[ERROR] Unable to load channel names: {e}')
        return None
    return channels


def fill_references(message, users, channels, files):
    """
    Fills in @mentions and #channels with their known display names
    :param message: Raw message to be filled with usernames and channel names instead of IDs
    :param users: Dictionary of user_id => display_name pairs
    :param channels: Dictionary of channel_id => channel_name pairs
    :return: Filled message string
    """
    MAX_MESSAGE_SIZE = 2000 - 60
    for uid, name in users.items():
        message = message.replace(f'<@{uid}>', f'@{name}')
    for cid, name in channels.items():
        message = message.replace(f'<#{cid}>', f'#{name}')

    files_msg = ''
    for file_url in files:
        files_msg = '\n'.join([files_msg, file_url])

    limit = MAX_MESSAGE_SIZE - len(files_msg)

    message = '\n'.join([message[:limit], files_msg]).strip('\n')
    return message


async def uploadd_file(channel, file_info):
    if 'image' in file_info['mimetype']:
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(file_info['url_private']) as resp:
                if resp.status != 200:
                    return await channel.send('Could not download file...')
                data = io.BytesIO(await resp.read())
                await channel.send(file=discord.File(data, file_info['name']))
    except Exception as e:
        print(
            f"[INFO] skip dowloading file ({e}) url: {file_info['url_private']}")
        pass


def register_commands():
    @bot.command(pass_context=True)
    async def import_here(ctx, *kwpath):
        """
        Attempts to import .json files from the specified path (relative to the bot) to the channel from which the
        command is invoked. Multiple paths can be passed, in which case the corresponding files will be imported in
        order.
        :param ctx:
        :param path:
        :return:
        """
        paths = list(kwpath)
        for path in paths:
            print(
                f"[INFO] Attempting to import '{path}' to channel '#{ctx.message.channel.name}'")
            json_file_paths = get_file_paths(path)

            if not json_file_paths:
                print(f'[ERROR] No .json files found at {path}')
            else:
                users = get_display_names(json_file_paths)
                if users:
                    print(f'[INFO] users.json found - attempting to fill @mentions')
                else:
                    print(
                        f'[WARNING] No users.json found - @mentions will contain user IDs instead of display names')

                channels = get_channel_names(json_file_paths)
                if channels:
                    print(
                        f'[INFO] channels.json found - attempting to fill #channel references')
                else:
                    print(
                        f'[WARNING] No channels.json found - #channel references will contain user IDs instead of names')

                for json_file in sorted(json_file_paths):
                    print(f'[INFO] Parsing file: {json_file}')
                    try:
                        with open(json_file, encoding='utf-8') as f:
                            for message in json.load(f):
                                if all(key in message for key in ['ts', 'text']) and any(k in message for k in ['user_profile', 'user']):
                                    if 'user_profile' in message:
                                        if message['user_profile']['display_name']:
                                            username = message['user_profile']['display_name']
                                        else:
                                            username = message['user_profile']['real_name']
                                    else:
                                        username = users[message['user']]
                                    timestamp = datetime.fromtimestamp(float(message['ts'])).strftime(
                                        '%m/%d/%Y at %H:%M:%S')
                                    files = [f.get('url_private')
                                             for f in message.get('files', [])]
                                    text = fill_references(
                                        message['text'], users, channels, files)
                                    msg = f'**{username}** *({timestamp})*\n{text}'
                                    await ctx.send(msg)
                                    channel = ctx.message.channel
                                    for file_info in message.get('files', []):
                                        await uploadd_file(channel, file_info)
                                    print(f"[INFO] Imported message: '{msg}'")
                                    time.sleep(THROTTLE_TIME_SECONDS)
                                else:
                                    print(
                                        '[WARNING] User information, timestamp, or message text missing')
                    except Exception as e:
                        print(f'[ERROR] {e}')
                print(f'[INFO] Import complete')


if __name__ == '__main__':
    bot = commands.Bot(command_prefix='!')
    register_commands()
    bot.run(input('Bot token: '))
