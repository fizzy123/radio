# pragma pylint: disable=missing-docstring, invalid-name, superfluous-parens
import sys
import re
import random
import subprocess
import sqlite3
import argparse

from os import listdir
from os.path import isfile, join
from dateutil import parser

import redis
import requests
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO

app = Flask(__name__, static_url_path='/static')
socketio = SocketIO(app)
#socketio = SocketIO(app, async_mode='threading')
r_client = redis.StrictRedis(host='localhost', port=6379, db=0)
conn = sqlite3.connect('radio.db')
conn.row_factory = sqlite3.Row

config = {}
MESSAGES_LENGTH = 100

@app.route("/", methods=['GET'])
def index():
    messages = r_client.lrange('messages', 0, MESSAGES_LENGTH)
    return render_template('index.html', messages=messages)

@app.route("/", methods=['POST'])
def topic_post():
    message = request.form['message']
    parse_message(message['raw'])
    r_client.rpush('messages', message['formatted'])
    length = r_client.llen('messages')
    r_client.ltrim('messages', length - MESSAGES_LENGTH, length)
    return jsonify({'success': True})

@app.route("/done")
def done():
    play_song()

def parse_message(message):
    if '++' in message and config['enable-upvotes']:
        upvote()
    elif '--' in message and config['enable-downvotes']:
        print('Downvoted!')
        downvote()
    elif message[0:4] and config['enable-adding']:
        print('Added!')
        response_text = "Added {} to the playlist!".format(message.split(' ')[1])
        socketio.emit('message', response_text)
        upvote(url=message.split(' ')[1])

def run():
    query = """SELECT url
               FROM songs
               ORDER BY RANDOM()
               LIMIT 1
            """
    config['staging_url'] = list(conn.cursor().execute(query))[0]['url']
    delete = subprocess.Popen(['rm', '-rf', '/tmp/staging.wav'], stdout=subprocess.PIPE)
    delete.wait()
    download = subprocess.Popen(['youtube-dl',
                                 '--extract-audio',
                                 '--audio-format',
                                 'wav',
                                 '-o',
                                 '/tmp/staging.wav',
                                 config['staging_url']], stdout=subprocess.PIPE)
    download.wait()
    play_song()

def play_song():
    swap = subprocess.Popen(['mv', '/tmp/staging.wav', '/tmp/current.wav'], stdout=subprocess.PIPE)
    config['current_url'] = config['staging_url']
    swap.wait()
    if swap.returncode != 0:
        raise RuntimeError('Swap Failed')
    image = random.choice([f for f in listdir('images') if isfile(join('images', f))])
    stream = subprocess.Popen(['./stream.sh',
                               image,
                               '{}/{}'.format(config['rtmp-server'],
                                              config['broadcast-title'].lower().replace(' ', '-'))
                              ])

    # Notify what track is playing!
    info = None
    if 'youtube' in config['current_url']:
        info = get_youtube_info()
    elif 'soundcloud' in config['current_url']:
        info = get_soundcloud_info()
    if info:
        response_text = "Coming up: {}".format(info)
        socketio.emit('message', response_text)
    query = """SELECT url
               FROM songs
               ORDER BY RANDOM()
               LIMIT 1
            """
    config['staging_url'] = list(conn.cursor().execute(query))[0]['url']
    delete = subprocess.Popen(['rm', '-rf', '/tmp/staging.wav'], stdout=subprocess.PIPE)
    delete.wait()
    if delete.returncode != 0:
        raise RuntimeError('Delete Failed')
    download = subprocess.Popen(['youtube-dl',
                                 '--extract-audio',
                                 '--audio-format',
                                 'wav',
                                 '-o',
                                 '/tmp/staging.wav',
                                 config['staging_url']], stdout=subprocess.PIPE)
    download.wait()
    if download.returncode != 0:
        raise RuntimeError('Download Failed')
    stream.wait()
    if stream.returncode != 0:
        raise RuntimeError('Stream Failed')

def get_youtube_info(url=None):
    if not url:
        url = config['current_url']
    video_id = re.search(r"\?v=([a-zA-z0-9\-]+)", url).group(1)
# pylint: disable=line-too-long
    response = requests.get('https://www.googleapis.com/youtube/v3/videos?id={}&key={}&part=snippet'.format(video_id, config['youtube_api_key']))
    title = response.json()[0]['title']
    return title

def get_soundcloud_info(url=None):
    if not url:
        url = config['current_url']
    parts = url.replace('-', ' ').split('/')
    return "{} - {}".format(parts[-2], parts[-1])

def init():
    # db structure is a little weird.
    # Rather than having a score explicitly, the score will be how many rows with that url exist.
    cur = conn.cursor()
    cur.execute("""CREATE TABLE songs (
                     id INTEGER PRIMARY KEY NOT NULL,
                     url TEXT NOT NULL
                   )
                """)
    conn.commit()

def upvote(times=1, url=None):
    if not url:
        url = config['current_url']
    print("{} upvotes for {}".format(times, url))
    cur = conn.cursor()
    cur.executemany("""INSERT INTO songs (url) values(?)""", [(url,)] * times)
    conn.commit()
    if config.get('broadcast-title'):
        dump(config['broadcast-title'].lower().replace(' ', '-'))

def downvote(times=1):
    print("{} downvotes for {}".format(times, config['current_url']))
    cur = conn.cursor()

    cur.execute("""DELETE FROM songs
                   WHERE id = (SELECT id
                               FROM songs
                               WHERE url=?
                               LIMIT ?)""", (config['current_url'], times,))
    conn.commit()
    dump(config['broadcast-title'].lower().replace(' ', '-'))

def dump(key):
    query = """SELECT url, count(*) as score
               FROM songs
               GROUP BY url
            """
    rows = list(conn.cursor().execute(query))

    row_list = [dict(zip(row.keys(), row)) for row in rows]
    row_list = sorted(row_list, key=lambda row: row['score'])
    result_string = "Full song list for {}\n\nsong|score\n".format(key)
    for row in row_list:
        info = None
        if 'youtube' in row['url']:
            info = get_youtube_info(row['url'])
        elif 'soundcloud' in row['url']:
            info = get_soundcloud_info(row['url'])
        result_string = result_string + info + '|' + str(row['score']) + '\n'
    result_string = result_string + "\n\n#readonly"
    requests.post('http://nobr.me/general/ram/', {'key': key, 'body': result_string})

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == 'init':
            init()
        elif sys.argv[1] == 'add':
            upvote(url=sys.argv[2])
        elif sys.argv[1] == 'dump':
            dump(sys.argv[2])
    parser = argparse.ArgumentParser(description='Host a radio website')
    parser.add_argument("--broadcast-title", help="Broadcast title",
                        default="Nobel Radio")
    parser.add_argument("--disable-upvotes", help="Disable Upvotes")
    parser.add_argument("--disable-downvotes", help="Disable Downvotes")
    parser.add_argument("--disable-adding", help="Disable Adding Songs")
    parser.add_argument("--description", help="Description")
    parser.add_argument("--rtmp-server", help="Description", default='172.17.0.1')
    args = parser.parse_args()
    if not args.description:
        args.description = ''
# pylint: disable=line-too-long
    args.description = "{}\n\nPlaylist: http://nobr.me/general/ram/?key={}".format(args.descrption, args.broadcast_title.lower().replace(' ', '-'))
    if not args.disable_upvotes or \
       not args.disable_downvotes or \
       not args.disable_adding:
        args.description = args.description + "\n\nCOMMANDS:\n"
        if not args.disable_upvotes:
# pylint: disable=line-too-long
            args.description = args.description + "++ - Upvote current song. More Upvoted songs will play more often\n"
        if not args.disable_downvotes:
# pylint: disable=line-too-long
            args.description = args.description + "-- - Downvote current song. More Downvoted songs will play less often\n"
        if not args.disable_adding:
            args.description = args.description + "!add {url} - Add a song from a url. Officially only supports youtube and soundcloud at the moment. Check the youtube link you put in for quality!\n"
    config['broadcast-title'] = args.broadcast_title
    config['rtmp-server'] = args.rtmp_server
    config['enable-upvotes'] = not args.disable_upvotes
    config['enable-downvotes'] = not args.disable_downvotes
    config['enable-adding'] = not args.disable_adding
    run()
    socketio.run(app, port=3000, debug=True, host='0.0.0.0')
